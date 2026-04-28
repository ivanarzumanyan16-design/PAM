//imports from this project
import { notify_update } from "./notifier.mjs" 

//imports from standard libraries
import { parse } from "url";
import { randomUUID} from "crypto";
import { connect } from "http2";

//imports from third party libraries

const trace = (m) => logger.trace("router", m);
const warning = (m) => logger.warning("router", m);
const error = (m) => logger.error("router", m);

const listened_uuids = {};
const wss_clients = {};

const metax_sessions = {};
let session_id_counter = 1;

//let log_active_sessions = setInterval(sessions_log.write, 10000, "current_session_count = " + metax_sessions);

export function handle_new_write_server_stream(stream, headers) {
	try {
		if(!stream.session.socket.authorized) {
			warning(`rejecting unauthorized request from ${stream.session.socket.remoteAddress}`);
			send_method_error(stream, "request is unauthorized, please insert a valid client certificate.", headers[":method"]);
			return;
		}
		if(headers[":path"] === undefined) {
			send_method_error(stream, "invalid path.", headers[":method"]);
			return;
		}
		const path = parse(headers[":path"], true).pathname;
		trace(`received new secure request: ${stream.session.id} path: ${path}, user_fingerprint: ${stream.session.socket.getPeerCertificate().fingerprint256}`);
		switch (path) {
			case "/db/get":
				handle_get_request(stream, headers);
				break;
			case "/db/save/data":
			case "/db/save/node":
				handle_save_request(stream, headers);
				break;
			case "/db/register_listener":
				handle_register_listener_request(stream, headers);
				break;
			case "/db/unregister_listener":
				handle_unregister_listener_request(stream, headers);
				break;
			case "/db/delete":
				handle_delete_request(stream, headers);
				break;
			case "/config/get_user_id":
				handle_get_user_id_request(stream, headers);
				break;
			case "/oo/wrap":
			case "/oo/get_property":
			case "/oo/set_property":
			case "/oo/get_property/embedded":
			case "/oo/set_property/embedded":
			case "/oo/add_element_to_collection":
			case "/oo/create_element_in_collection":
			case "/oo/create_element_in_collection/embedded":
			case "/oo/delete_element_from_collection":
			case "/oo/delete_element_from_collection/embedded":
			case "/oo/delete_element_from_embedded_collection":
			case "/oo/create_element_in_embedded_collection":
				handle_odm_request(stream, headers);
				break;
			default:
				send_method_error(stream, "request is not handled yet.", headers[":method"]);
				break;
		}
		stream.on("error", err => error(err));
	} catch(e) {
		error(e);
	}
}

export function handle_new_read_only_stream(stream, headers) {
	try {
		if (headers[":method"] !== "GET") {
			send_method_error(stream, `received read-only request with method ${headers[":method"]}.`, headers[":method"]);
			return
		}
		if(headers[":path"] === undefined) {
			send_error(res, "invalid path.");
			return;
		}
		const path = parse(headers[":path"], true).pathname;
		trace(`received new stream from ${stream.session.id}, path: ${path}`);
		switch (path) {
			case "/db/get":
				handle_get_request(stream, headers);
				break;
			case "/oo/wrap":
			case "/oo/get_property":
				handle_odm_request(stream, headers);
				break;
			default: 
				handle_default_request(stream, headers);
				break;
		}
	} catch(e) {
		error(e);
	}
}

export function handle_new_client_session(session) {
	session.id = session_id_counter++;
	sessions_log.write("new session: " + session.socket.remoteAddress + "  , session id: " + session.id + "\n");
	metax_sessions[session.id] = connect(`https://${config.host_metax}`);
        session.on("close", () => {
		metax_sessions[session.id].close();
		delete metax_sessions[session.id];
	});
        session.on("error", e => {
                error(e);
        });
        metax_sessions[session.id].on("error", (e) => {
                error(`metax error: ${e}`)
        });
        session.on("goaway", () => {
                trace(`session ${session.id} goaway frame received`);
        });
        //session.setTimeout(120000);
        //session.on('timeout', () => session.close() );
}

export function handle_metax_update_message(uuid) {
	assert(is_valid_uuid(uuid), "handle_metax_update_message received invalid uuid.");
	trace("received handle_metax_update_message with uuid: " + uuid)
	if(listened_uuids[uuid] !== undefined) {
		for(let i = 0; i < listened_uuids[uuid].length; i++) {
			let token = listened_uuids[uuid][i];
			assert(wss_clients[token] !== undefined,
				"listened_uuids has token in list, but websocket object not found.");
			trace("sending update_message for uuid: " + uuid + " to token: " + token);
			wss_clients[token].send(JSON.stringify({event: "update", uuid}))
		}
	}
}

export function handle_websocket_new_connection(s) {
	const token = randomUUID();
	wss_clients[token] = s;
	s.send(`{"event":"connected", "token": "${token}"}`);
	s.on("pong", () => s.isAlive = true);
	const send_ping = setInterval(() => {
		if(s.isAlive === false) {
			return s.terminate()
		};
		s.isAlive = false;
		s.ping();
	}, 30000);
	s.on("close", () => {
		trace(`received websocket close event for session: ${token}`);
		assert(wss_clients[token] !== undefined,
			"websocket connection was closed improperly");
		clearInterval(send_ping);
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

function handle_get_user_id_request(stream, headers) {
	trace(`processing get_user_id request with path ${headers[":path"]}`);
	try {
		if (headers[":method"] !== "GET") {
			send_method_error(stream, `received /config/get_user_id request with method ${headers[":method"]}`, headers[":method"]);
			return;
		}
		let i = sitemap.websites.findIndex(website => {
			let index = website.subdomains.findIndex(el => el.name === headers[":authority"].split(":")[0])
			return index !== -1;
		});
		if(i !== -1) {
			let client_key = stream.session.socket.getPeerCertificate().raw.toString('base64');
			let j = sitemap.websites[i].client_certificates.findIndex(el =>
								el["certificate"]
									.replace(/[\r\n]/gm, '')
									.replace(/[\n]/gm, '')
									.includes(client_key));
			if(j !== -1) {
				stream.respond({":status": 200,
					"content-type":"application/json"});
				let user_id = sitemap.websites[i].client_certificates[j]["user_id"];
				stream.end(JSON.stringify({ "user_id": user_id || "no defined yet"}));
			} else {
				stream.respond({":status": 400,
					"content-type":"application/json"});
				stream.end(JSON.stringify({error: "couldn't find user."}));
			}
		} else {
			stream.respond({":status": 400,
				"content-type":"application/json"});
			stream.end(JSON.stringify({error: "couldn't find user."}));
		}
	} catch(e) {
		error(e);
	}
}

async function handle_unregister_listener_request(stream, headers) {
	trace(`processing unregister_listener request with path ${headers[":path"]}`);
	const { id, token } = parse(headers[":path"], true).query;
	if (headers[":method"] !== "GET") {
		send_method_error(stream, `received /db/unregister_listener with request method ${headers[":method"]}`, headers[":method"]);
		return;
	}
	if(!is_valid_uuid(id)) {
		send_error(stream, `invalid uuid.`);
		return;
	}
	if(!is_valid_uuid(token)
		|| wss_clients[token] === undefined) {
		send_error(stream, `session token not found.`);
		return;
	}
	if(listened_uuids[id] === undefined
		|| listened_uuids[id].indexOf(token) === -1) {
		send_error(stream, `no listener register for ${id} in this session.`);
		return;
	}
	listened_uuids[id].splice(listened_uuids[id].indexOf(token), 1);
	if(listened_uuids[id].length === 0) {
		delete listened_uuids[id];
	}
	await metax_unregister_listener(id)
		.then(r => JSON.parse(r))
		.then(r => {
			if(r.status !== "success") {
				error("failed to register_listener");
				return;
			}
		})
		.catch(e => {
			error(e);
		});
	stream.respond({":status": 200,
		"content-type":"application/json"});
	stream.end(`{"status":"success"}`);
}

async function handle_register_listener_request(stream, headers) {
	trace(`processing register_listener request with path ${headers[":path"]}`);
	const { id, token } = parse(headers[":path"], true).query;
	if (headers[":method"] !== "GET") {
		send_method_error(stream, `received /db/register_listener with request method ${headers[":method"]}`, headers[":method"]);
		return;
	}
	if(!is_valid_uuid(id)) {
		send_error(stream, `invalid uuid.`);
		return;
	}
	if(!is_valid_uuid(token)
		|| wss_clients[token] === undefined) {
		send_error(stream, `session token not found.`);
		return;
	}
	await metax_register_listener(id)
		.then(r => JSON.parse(r))
		.then(r => {
			if(r.status !== "success") {
				send_error(stream, "failed to register_listener");
				return;
			}
			add_uuid_in_listened_uuids(id, token, stream);
		})
		.catch(e => {
			if (e.toString().includes(`listener was already registered`)) {
				return add_uuid_in_listened_uuids(id, token, stream);
			}
			error(e);
			send_error(stream, e);
		});
}

function add_uuid_in_listened_uuids(id, token, stream) {
	if(listened_uuids[id] === undefined) {
		listened_uuids[id] = [];
	}
	if(listened_uuids[id].indexOf(token) === -1) {
		listened_uuids[id].push(token);
		stream.respond({ ":status": 200,
				"content-type": "application/json"});
		stream.end(`{"status":"success"}`);
	} else {
		send_error(stream, `listener was already registered for this uuid`);
	}
}

function handle_save_request(stream, headers) {
	trace(`processing /db/save request with path ${headers[":path"]}, user_fingerprint: ${stream.session.socket.getPeerCertificate().fingerprint256}.`);
	if (headers[":method"] !== "POST") {
		send_method_error(stream, `received /db/save with request method ${headers[":method"]}`, headers[":method"]);
		return;
	}
	const query_object = parse(headers[":path"], true).query;
	const save_request = metax_sessions[stream.session.id].request(headers)
		.on("response", respHeaders => {
			try {
				stream.respond(respHeaders);
				save_request.pipe(stream);
				save_request.on("end", () => {
					trace(`finished /db/save request with path ${headers[":path"]}.`);
				});
				if(respHeaders[":status"] === 200 && 
					query_object["notify"] === "true" &&
					is_valid_uuid(query_object["id"])) {
					notify_update(
						query_object["id"],
						stream.session.socket.getPeerCertificate(),
						headers
					);
				}
			} catch(e) {
				error(e);
			}
		})
		.on("error", err => {
			error(err);
		});
	stream.pipe(save_request);
}

function handle_odm_request(stream, headers) {
	trace(`processing odm request with path ${headers[":path"]}.`);
	if (headers[":method"] !== "GET" && headers[":method"] !== "POST") {
		send_method_error(stream, `received /oo request with method ${headers[":method"]}`, headers[":method"]);
		return;
	}
	const save_request = metax_sessions[stream.session.id].request(headers)
		.on("response", respHeaders => {
			try {
				stream.respond(respHeaders);
			} catch(e) {
				error(e);
			}
			save_request.pipe(stream);
			save_request.on("end", () => {
				trace(`finished odm request with path ${headers[":path"]}.`);
			});
		})
		.on("error", err => {
			error(err);
		});
	if (headers[":method"] === "POST") {
		stream.pipe(save_request);
        }
}

function handle_delete_request(stream, headers) {
	const query_object = parse(headers[":path"], true).query;
	if (headers[":method"] !== "GET") {
		send_method_error(stream, `received /db/delete with request method ${headers[":method"]}`, headers[":method"]);
		return;
	}
	if(query_object.id !== undefined) {
		query_object.id = query_object.id.split("?")[0];
	}
	if(is_valid_uuid(query_object.id)) {
		trace(`processing /db/get for ${query_object.id}`);
		const get_request = metax_sessions[stream.session.id].request(headers)
			.on("response", respHeaders => {
				try {
					stream.respond(respHeaders);
					get_request.pipe(stream);
					get_request.on("end", () => {
						stream.end();
						trace(`finished /db/get for ${query_object.id}`);
					});
				} catch(e) {
					error(e);
				}
			})
			.on("error", err => {
				error(err);
			})
		stream.on("close", () => get_request.close())
	} else {
		send_error(stream, "invalid uuid.");
	}
}

function handle_get_request(stream, headers) {
	const query_object = parse(headers[":path"], true).query;
	if (headers[":method"] !== "GET") {
		send_method_error(stream, `received /db/get with request method ${headers[":method"]}`, headers[":method"]);
		return;
	}
	if(query_object.id !== undefined) {
		query_object.id = query_object.id.split("?")[0];
	}
	if(is_valid_uuid(query_object.id)) {
		trace(`processing /db/get for ${query_object.id}`);
		const get_request = metax_sessions[stream.session.id].request(headers)
			.on("response", respHeaders => {
				try {
					stream.respond(respHeaders);
				} catch(e) {
					error(e);
				}
			})
                        .on("data", d => {
				try {
					if (!stream.closed) {
						stream.write(d);
					} else {
						error("Stream closed cannot write data.");
					}
				} catch(e) {
					error(e);
				}
			})
                        get_request.on("end", () => {
                                get_request.close();
                                stream.end();
                                trace(`finished /db/get for ${query_object.id}`);
                        })
                        .on("error", err => {
                                stream.end();
                                error(err);
                        })
                stream.on("close", () => get_request.close());
	} else {
		send_error(stream, "invalid uuid.");
	}
}

function handle_default_request(stream, headers) {
	const req_path = parse(headers[":path"], true).pathname;
	trace("received default request from "+ headers[":authority"] +" with path " + req_path);
	if(headers[":method"] !== "GET") {
		send_error(stream, `received request wrong method: ${headers[":method"]}.`);
	}
	for (let i = 0; i < sitemap.websites.length; i++) {
		const subdomain = sitemap.websites[i].subdomains.find(s => s.name === headers[":authority"]);
		if (subdomain === undefined) { continue }
		const path = subdomain.paths.find(p => p.name === req_path);
		if (path === undefined || !is_valid_uuid(path.destination_uuid)) {
			send_error(stream, "request not handled yet.");
			return;
		}
		const req_headers = { ":path": `/db/get?id=${path.destination_uuid}` };
		trace("piping default request with path " + req_path);
		const get_request = metax_sessions[stream.session.id].request(req_headers)
			.on("response", respHeaders => {
				if(!stream.destroyed) {
					stream.respond(respHeaders);
					get_request.pipe(stream);
					get_request.on("end", () => {
						stream.end();
						trace(`finished handle default request`);
					});
				}
			})
			.on("error", err => {
				error(err);
			});
		return;
	}
	trace("skipping default request with path " + req_path);
	send_error(stream, "request not handled yet.");
}

function send_method_error(res, msg, method) {
	if(method === "HEAD") {
		res.respond({
			":status"	: 400
			,	"content-type"	: "plain/text"
		});
		res.end();
	} else {
		send_error(res, msg);
	}
}

function send_error(res, msg) {
        res.respond({
			":status"	: 400
		,	"content-type"	: "application/json"
	});
        res.write(`{"error":"${msg}"}`);
	res.end();
}
