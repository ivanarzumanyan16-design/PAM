//imports from this project
import {
		initialize_db
	,	get_uuid
	,	save_uuid
	,	delete_uuid
} from "./db.mjs";

//imports from standard libraries
import { parse } from "url";

//imports from third party libraries

export function initialize_db_rest_api() {
	initialize_db();
}

export function handle_db_request(req, res) {
	if(req.headers[":path"] === undefined ) {
		send_error(res, "request is not handled yet.");
		return;
	}
	let req_path = req.headers[":path"].split("?")[0];
	assert(req_path.split("/")[1] === "db",
		"handle_db_request received non-db request");
	console.log(`handling db request`,
		`request path: ${req.headers[":path"]}`);
	switch(req_path) {
		case "/db/get":
			handle_get_request(req, res);
			break;
		case "/db/save/node":
		case "/db/save/data":
			handle_save_request(req, res);
			break;
		case "/db/delete":
			handle_delete_request(req, res);
			break;
		case "/db/register_listener":
			handle_register_listener_request(req, res);
			break;
		case "/db/unregister_listener":
			handle_unregister_listener_request(req, res);
			break;
		default:
			send_error(res, "request is not handled yet.");
			break;
	}
}

function send_error(res, msg) {
	res.writeHead(400, {"content-type": "application/json"});
	res.end(`{"error":"${msg}"}`);
}

function handle_unregister_listener_request(req, res) {
	console.log(`received unregister_listener request with path ${req.headers[":path"]}`);
	const query_object = parse(req.headers[":path"], true).query;
	if (req.method !== "GET") {
        	send_error(res, `received /db/unregister_listener with request method ${req.method}`);
		return;
	}
	const { id, token } = query_object;
	if(!is_valid_uuid(id)) {
		send_error(res, `invalid uuid.`);
		return;
	}
	if(!is_valid_uuid(token)
		|| wss_clients[token] === undefined) {
		send_error(res, `session token not found.`);
		return;
	}
	if(listened_uuids[id] === undefined
		|| listened_uuids[id].indexOf(token) === -1) {
		send_error(res, `no listener register for ${id} in this session.`);
		return;
	}
	listened_uuids[id].splice(listened_uuids[id].indexOf(token), 1);
	if(listened_uuids[id].length === 0) {
		delete listened_uuids[id];
	}
	res.writeHead(200, {"content-type": "application/json"});
	res.end(`{"status":"success"}`);
}

function handle_register_listener_request(req, res) {
	console.log(`received register_listener request with path ${req.headers[":path"]}`);
	const query_object = parse(req.headers[":path"], true).query;
	if (req.method !== "GET") {
        	send_error(res, `received /db/register_listener with request method ${req.method}`);
		return;
	}
	const { id, token } = query_object;
	if(!is_valid_uuid(id)) {
		send_error(res, `invalid uuid.`);
		return;
	}
	if(!is_valid_uuid(token)
		|| wss_clients[token] === undefined) {
		send_error(res, `session token not found.`);
		return;
	}
	if(listened_uuids[id] === undefined) {
		listened_uuids[id] = [];
	}
	if(listened_uuids[id].indexOf(token) === -1) {
		listened_uuids[id].push(token);
		res.writeHead(200, {"content-type": "application/json"});
		res.end(`{"status":"success"}`);
	} else {
		send_error(res, `listener was already registered for this uuid`);
	}
}

function handle_get_request(req, res) {
	console.log(`received get request with path ${req.headers[":path"]}`);
	const query_object = parse(req.headers[":path"], true).query;
	if(query_object.id !== undefined) {
		query_object.id = query_object.id.split("?")[0];
	}
	if (req.method !== "GET") {
        	send_error(res, `received /db/get with request method ${req.method}`);
		return;
	}
	if(!is_valid_uuid(query_object.id)) {
		send_error(res, `invalid uuid.`);
		return;
	}
	try {
		const range = req.headers["range"];
                const [start_byte, end_byte] = range ? 
                        range.slice(6).split("-").map(Number) : [0];
		const chunking = query_object.chunking !== "false";
		const get = get_uuid(query_object.id, start_byte, end_byte, chunking);
		assert(get.type === "full" || get.type === "partial", `get_uuid returned invalid type, ${get.type}`);
		assert(get.length !== undefined, `get_uuid did not return content length.`);
		if(get.type === "full") {
			res.setHeader("Content-Length", get.length);
			res.writeHead(200, {"content-type": get.mime});
		} else if (get.type === "partial") {
			res.setHeader("Content-Length", get.end_byte - start_byte + 1);
			res.setHeader("Content-Range", `bytes ${start_byte}-${get.end_byte}/${get.length}`);
			res.setHeader("Accept-Ranges", `bytes`);
			res.writeHead(206, {"content-type": get.mime});
		}
		get.data_stream.pipe(res);
		res.on("finish", () => {
			console.log("finish handling get request for " + query_object.id);
			res.end();
		});
		req.on("aborted", e => {
                        get.data_stream.close();
			console.log("aborted request for " + query_object.id);
                })
	} catch(e) {
		send_error(res, e);
	}
}

async function handle_save_request(req, res) {
	console.log(`received save request with path ${req.headers[":path"]}`);
	const query_object = parse(req.headers[":path"], true).query;
	if (req.method !== "POST") {
        	send_error(res, `received /db/save with request method ${req.method}`);
		return;
	}
	if(req.headers["content-type"] === undefined
		&& req.headers["Metax-Content-Type"] === undefined) {
		send_error(res, "content-type of body not specified in request.")
		return;
	}
	let save_type = req.headers[":path"].split("?")[0].split("/")[3];
	assert(save_type === "node" || save_type === "data", "received save request with invalid path");
	try {
		let content_type =
			req.headers["Metax-content-type"] !== undefined ?
			req.headers["Metax-content-type"] :
			req.headers["content-type"];
		const uuid = await save_uuid(
			req, content_type, save_type, query_object.id);
		send_notification_to_websocket_clients(uuid);
		assert(is_valid_uuid(uuid), "save_uuid returned invalid uuid");
		res.writeHead(200, {"content-type": "application/json"});
		res.end(`{"uuid": "${uuid}"}`);
	} catch(e) {
		send_error(res, e);
	}
}

function handle_delete_request(req, res) {
	console.log(`received delete request with path ${req.headers[":path"]}`);
	const query_object = parse(req.headers[":path"], true).query;
	if (req.method !== "GET") {
        	send_error(res, `received /db/delete with request method ${req.method}`);
		return;
	}
	if(!is_valid_uuid(query_object.id)) {
		send_error(res, `invalid uuid.`);
		return;
	}
	try {
		delete_uuid(query_object.id);
		res.writeHead(200, {"content-type":"application/json"});
		res.end(`{"status":"success", "uuid": "${query_object.id}"}`);
	} catch(err) {
		send_error(res, err);
	}
}
