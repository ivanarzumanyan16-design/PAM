//imports from this project
import {
		initialize_db_rest_api
	,	handle_db_request
} from "./db_rest_api.mjs";

import { handle_odm_request } from "./odm_rest_api.mjs";

//imports from standard libraries
import { createSecureServer } from "http2";
import { readFileSync } from "fs";
import { randomUUID } from "crypto";

//imports from third party libraries
import { WebSocketServer } from "ws";

const config = {};

process.on('uncaughtException', (err, origin) => {
        console.log(new Date(), "Uncaught exception", err, origin)
        process.exit(-1);
})

global.wss_clients = {};
global.listened_uuids = {};

global.config = config;
global.assert = (c, m) => {
	if(!c) {
		console.error("Assertion violation: ", m);
		process.exit(-1);
	}
}

global.is_valid_uuid = (u) => {
	return /^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$/i.test(u) ||
		/^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}-[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$/i.test(u);
}

main();

function main() {
	configure_metax();
	assert(config.storage !== undefined, "storage path is not defined.");
	assert(config.port !== undefined, "port is not defined.");
	assert(config.key !== undefined, "private key path is not defined.");
	assert(config.cert !== undefined, "certificate path is not defined.");
	initialize_db_rest_api();
	start_server();
}

function configure_metax() {
	const argv = process.argv.slice(2);
	for(let i = 0; i < argv.length; i++) {
		let pairs = argv[i].split("=");
		config[pairs[0]] = pairs[1];
	}
	console.log("metax configured.");
}

function start_server() {
	assert(!isNaN(parseInt(config.port)), "port must be a number.");
	const http_server = createSecureServer({
		peerMaxConcurrentStreams: 1000,
		key: readFileSync(config.key),
		cert: readFileSync(config.cert),
		allowHTTP1: true
	}, route_incoming_request);
	http_server.on("error", handle_http_server_error)
	http_server.listen(parseInt(config.port),
		() => console.log("https server started"));
	const wss = new WebSocketServer({ server: http_server });
	wss.on("connection", handle_websocket_new_connection);
}

function handle_http_server_error(e) {
	switch(e.code) {
		case "EADDRINUSE":
			console.error(`the port ${config.port} is already in use`);
			process.exit(-1);
			break;
		default:
			console.error("Unhandled server error", e);
	}
}

function route_incoming_request(req, res) {
	if(req.socket.alpnProtocol === "http/1.1") {
		console.log(`rejecting http/1.1 request from ${req.socket.remoteAddress}`);
		res.writeHead(400, {"content-type":"application/json"});
		res.end(`{"error": "rest_api only supports http/2 protocol"}`);
		return;	
	}
	//res.setHeader('Cross-Origin-Opener-Policy', 'same-origin');
	//res.setHeader('Cross-Origin-Embedder-Policy', 'require-corp');
	let req_path = req.headers[":path"].split("?")[0];
	console.log(`received new request from ${req.socket.remoteAddress},`,
		`request path: ${req.headers[":path"]}`);
	switch(req_path.split("/")[1]) {
		case "db":
			handle_db_request(req, res);
			break;
		case "oo":
			handle_odm_request(req, res);
			break;
		default:
			res.writeHead(400, {"content-type":"application/json"});
			res.end(`{"error":"request is not handled yet."}`);
			break;
	}
}

function handle_websocket_new_connection(s) {
        const token = randomUUID();
        wss_clients[token] = s;
        s.send(`{"event":"connected", "token": "${token}"}`);
        s.on("close", () => {
		console.log(`received websocket close event for session: ${token}`);
		assert(wss_clients[token] !== undefined,
			"websocket connection was closed improperly");
		delete wss_clients[token];
		clean_up_listened_uuids_per_token(token);
	});
}

function clean_up_listened_uuids_per_token(token) {
	const uuids = Object.keys(listened_uuids);
	for(let i = 0; i < uuids.length; i++) {
		let token_index = listened_uuids[uuids[i]].indexOf(token);
		if(token_index !== -1) {
			listened_uuids[uuids[i]].splice(token_index, 1);
		}
	}
}

global.send_notification_to_websocket_clients = (uuid) => {
	if(listened_uuids[uuid] !== undefined) {
		for(let i = 0; i < listened_uuids[uuid].length; i++) {
			let token = listened_uuids[uuid][i];
			assert(wss_clients[token] !== undefined,
				"listened_uuids has token in list, but websocket object not found.");
			wss_clients[token].send(JSON.stringify({event: "update", uuid}))
		}
	}
}


