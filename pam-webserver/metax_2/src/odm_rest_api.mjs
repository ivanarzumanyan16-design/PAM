//imports from this project
import {
                get_property_in_owned_object
        ,       get_property_in_embedded_object
        ,       set_property_in_owned_object
        ,       set_property_in_embedded_object
        ,       get_collection
        ,       add_element_to_collection
        ,       create_element_in_collection
        ,       create_element_in_embedded_collection
        ,       create_element_in_embedded_objects_collection
        ,       delete_element_from_collection
        ,       delete_element_from_embedded_collection
        ,       delete_element_from_embedded_objects_collection
        ,       wrap_owned_object
} from './odm.mjs'

//imports from standard libraries
import { parse } from "url";

//imports from third party libraries

export function handle_odm_request(req, res) {
	let req_path = req.headers[":path"].split("?")[0];
	assert(req_path.split("/")[1] === "oo",
		"handle_odm_request received non-oo request");
	console.log(`handling odm request`,
		`request path: ${req.headers[":path"]}`);
	switch(req_path) {
		case "/oo/get_property":
                        handle_get_property_request(req, res);
			break;
		case "/oo/get_property/embedded":
                        handle_get_property_in_embedded_object_request(req, res);
			break;
		case "/oo/set_property":
                        handle_set_property_request(req, res);
			break;
		case "/oo/set_property/embedded":
                        handle_set_property_in_embedded_object_request(req, res);
			break;
		case "/oo/get_collection":
                        handle_get_collection_request(req, res);
			break;
		case "/oo/add_element_to_collection":
                        handle_add_element_to_collection_request(req, res);
			break;
		case "/oo/create_element_in_collection":
                        handle_create_element_in_collection_request(req, res);
			break;
		case "/oo/create_element_in_collection/embedded":
                        handle_create_element_in_embedded_objects_collection_request(req, res);
			break;
		case "/oo/delete_element_from_collection":
                        handle_delete_element_from_collection_request(req, res);
			break;
		case "/oo/delete_element_from_collection/embedded":
                        handle_delete_element_from_embedded_objects_collection_request(req, res);
			break;
		case "/oo/create_element_in_embedded_collection":
                        handle_create_element_in_embedded_collection_request(req, res);
			break;
		case "/oo/delete_element_from_embedded_collection":
                        handle_delete_element_from_embedded_collection_request(req, res);
			break;
		case "/oo/wrap":
                        handle_wrap_request(req,res);
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

function handle_get_property_request(req, res) {
	console.log(`received get_property request with path ${req.headers[":path"]}`);
	const query_object = parse(req.headers[":path"], true).query;
	if (req.method !== "GET") {
        	send_error(res, `received /oo/get_property with request method ${req.method}`);
		return;
	}
        const {id, property, locale} = query_object;
	if(!is_valid_uuid(id)) {
		send_error(res, `Invalid uuid.`);
		return;
	}
        if(!property) {
                send_error(res, `Missing property id`);
                return
        }
        try {
                const value = get_property_in_owned_object(id, property, locale || "en_US");
                res.writeHead(200, {"content-type": "application/json"});
		const response = { value }
                res.end(JSON.stringify(response));
        } catch(e) {
                send_error(res, e);
        }
}

function handle_get_property_in_embedded_object_request(req, res) {
	console.log(`received get_property request with path ${req.headers[":path"]}`);
	const query_object = parse(req.headers[":path"], true).query;
	if (req.method !== "POST") {
        	send_error(res, `received /oo/get_property/embedded with request method ${req.method}`);
		return;
	}
        const {id, property, locale} = query_object;
	if(!is_valid_uuid(id)) {
		send_error(res, `Invalid uuid.`);
		return;
	}
        if(!property) {
                send_error(res, `Missing property id`);
                return
        }
        let data = '';
        req.on('data', (chunk) => {
                data += chunk;
        }).on('end', () => {
                try {
                        data = JSON.parse(data);
                } catch (e) {
                        send_error(res, "Request body is not valid json."); 
                }
                try {
                        const value = get_property_in_embedded_object(id, property, data, locale || "en_US");
                        res.writeHead(200, {"content-type": "application/json"});
                        res.end(`{"value":"${value}"}`);
                } catch(e) {
                        send_error(res, e);
                }
        }).on('error', (e) => {
                send_error(res, 'Failed get request body');
        })
}

function handle_set_property_request(req, res) {
	console.log(`received set_property request with path ${req.headers[":path"]}`);
	const query_object = parse(req.headers[":path"], true).query;
	if (req.method !== "POST") {
        	send_error(res, `received /oo/set_property with request method ${req.method}`);
		return;
	}
        const {id, property, locale} = query_object;
	if(!is_valid_uuid(id)) {
		send_error(res, `Invalid uuid.`);
		return;
	}
        if(!property) {
                send_error(res, `Missing property id`);
                return
        }
        let value = '';
        req.on('data', (chunk) => {
                value += chunk;
        }).on('end', () => {
                try {
                        let response = set_property_in_owned_object(id, property, value, locale || "en_US");
                        send_notification_to_websocket_clients(id);
                        res.writeHead(200, {"content-type": "application/json"});
                        res.end(JSON.stringify({"value": response}));
                } catch(e) {
                        send_error(res, e);
                }
        }).on('error', (e) => {
                send_error(res, 'Failed get request body');
        })
}

function handle_set_property_in_embedded_object_request(req, res) {
	console.log(`received set_property request with path ${req.headers[":path"]}`);
	const query_object = parse(req.headers[":path"], true).query;
	if (req.method !== "POST") {
        	send_error(res, `received /oo/set_property/embedded with request method ${req.method}`);
		return;
	}
        const {id, property, locale} = query_object;
	if(!is_valid_uuid(id)) {
		send_error(res, `Invalid uuid.`);
		return;
	}
        if(!property) {
                send_error(res, `Missing property id`);
                return
        }
        let data = '';
        req.on('data', (chunk) => {
                data += chunk;
        }).on('end', () => {
                try {
                        data = JSON.parse(data);
                } catch (e) {
                        send_error(res, "Request body is not valid json."); 
                }
                try {
                        let response = set_property_in_embedded_object(id, property, data.value, data.child, locale || "en_US");
                        if (typeof response === "object") {
                                response = JSON.stringify(response);
                        } else {
                                response = `"${response}"`;
                        }
                        res.writeHead(200, {"content-type": "application/json"});
                        res.end(`{"value": ${response}}`);
                } catch(e) {
                        send_error(res, e);
                }
        }).on('error', (e) => {
                send_error(res, 'Failed get request body');
        })
}

function handle_get_collection_request(req, res) {
	console.log(`received get_collection request with path ${req.headers[":path"]}`);
	const query_object = parse(req.headers[":path"], true).query;
	if (req.method !== "GET") {
        	send_error(res, `received /oo/get_collection with request method ${req.method}`);
		return;
	}
        const {id, collection, property, locale} = query_object;
	if(!is_valid_uuid(id)) {
		send_error(res, `Invalid uuid.`);
		return;
	}
        if(!collection) {
                send_error(res, `Missing property id`);
                return
        }
        try {
                const value = get_collection(id, collection, property, locale || "en_US");
                res.writeHead(200, {"content-type": "application/json"});
		const response = { collection : value }
                res.end(JSON.stringify(response));
        } catch(e) {
                send_error(res, e);
        }
}

function handle_add_element_to_collection_request(req, res) {
	console.log(`received add_element_to_collection request with path ${req.headers[":path"]}`);
	const query_object = parse(req.headers[":path"], true).query;
	if (req.method !== "GET") {
        	send_error(res, `received /oo/add_element_to_collection with request method ${req.method}`);
		return;
	}
        const {id, collection, element} = query_object;
	if(!is_valid_uuid(id)) {
		send_error(res, `Invalid uuid.`);
		return;
	}
        if(!collection) {
                send_error(res, `Missing collection id`);
                return
        }
	if(!is_valid_uuid(element)) {
		send_error(res, `Invalid element uuid.`);
		return;
	}
        try {
                add_element_to_collection(id, collection, element);
                send_notification_to_websocket_clients(id);
                res.writeHead(200, {"content-type": "application/json"});
                res.end(`{"uuid":"${element}"}`);
        } catch(e) {
                send_error(res, e);
        }
}

function handle_create_element_in_collection_request(req, res) {
	console.log(`received create_element_in_collection request with path ${req.headers[":path"]}`);
	const query_object = parse(req.headers[":path"], true).query;
	if (req.method !== "GET") {
        	send_error(res, `received /oo/create_element_in_collection with request method ${req.method}`);
		return;
	}
        const {id, collection} = query_object;
	if(!is_valid_uuid(id)) {
		send_error(res, `Invalid uuid.`);
		return;
	}
        if(!collection) {
                send_error(res, `Missing collection id`);
                return
        }
        try {
                const uuid = create_element_in_collection(id, collection);
                send_notification_to_websocket_clients(id);
                res.writeHead(200, {"content-type": "application/json"});
                res.end(`{"uuid":"${uuid}"}`);
        } catch(e) {
                send_error(res, e);
        }
}

function handle_create_element_in_embedded_collection_request(req, res) {
	console.log(`received create_element_in_collection request with path ${req.headers[":path"]}`);
	const query_object = parse(req.headers[":path"], true).query;
	if (req.method !== "GET") {
        	send_error(res, 
                        `received /oo/create_element_in_embedded_collection with request method ${req.method}`);
		return;
	}
        const {id, collection} = query_object;
	if(!is_valid_uuid(id)) {
		send_error(res, `Invalid uuid.`);
		return;
	}
        if(!collection) {
                send_error(res, `Missing collection id`);
                return
        }
        try {
                const object = create_element_in_embedded_collection(id, collection);
                send_notification_to_websocket_clients(id);
                res.writeHead(200, {"content-type": "application/json"});
                res.end(JSON.stringify(object));
        } catch(e) {
                send_error(res, e);
        }
}

function handle_create_element_in_embedded_objects_collection_request(req, res) {
	console.log(`received create_element_in_collection request with path ${req.headers[":path"]}`);
	const query_object = parse(req.headers[":path"], true).query;
	if (req.method !== "POST") {
        	send_error(res, 
                        `received /oo/create_element_in_collection/embedded with request method ${req.method}`);
		return;
	}
        const {id, collection} = query_object;
	if(!is_valid_uuid(id)) {
		send_error(res, `Invalid uuid.`);
		return;
	}
        if(!collection) {
                send_error(res, `Missing collection id`);
                return
        }
        let data = '';
        req.on('data', (chunk) => {
                data += chunk;
        }).on('end', () => {
                try {
                        data = JSON.parse(data);
                } catch (e) {
                        send_error(res, "Request body is not valid json."); 
                        return
                }
                try {
                        const new_element = create_element_in_embedded_objects_collection(id, collection, data);
                        res.writeHead(200, {"content-type": "application/json"});
                        res.end(JSON.stringify(new_element));
                } catch(e) {
                        send_error(res, e);
                }
        }).on('error', (e) => {
                send_error(res, 'Failed get request body');
        })
}

function handle_delete_element_from_collection_request(req, res) {
	console.log(`received delete_element_from_collection request with path ${req.headers[":path"]}`);
	const query_object = parse(req.headers[":path"], true).query;
	if (req.method !== "GET") {
        	send_error(res, `received /oo/delete_element_from_collection with request method ${req.method}`);
		return;
	}
        const {id, collection, element} = query_object;
	if(!is_valid_uuid(id)) {
		send_error(res, `Invalid uuid.`);
		return;
	}
        if(!collection) {
                send_error(res, `Missing collection id`);
                return
        }
        try {
                const deleted_uuid = delete_element_from_collection(id, collection, element);
                send_notification_to_websocket_clients(id);
                res.writeHead(200, {"content-type": "application/json"});
                res.end(`{"deleted":"${deleted_uuid}"}`);
        } catch(e) {
                send_error(res, e);
        }
}

function handle_delete_element_from_embedded_collection_request(req, res) {
	console.log(`received delete_element_from_collection request with path ${req.headers[":path"]}`);
	const query_object = parse(req.headers[":path"], true).query;
	if (req.method !== "GET") {
        	send_error(res, 
                        `received /oo/delete_element_from_embedded_collection with request method ${req.method}`);
		return;
	}
        const {id, collection, index} = query_object;
	if(!is_valid_uuid(id)) {
		send_error(res, `Invalid uuid.`);
		return;
	}
        if(!collection) {
                send_error(res, `Missing collection id`);
                return
        }
        try {
                const delete_status = delete_element_from_embedded_collection(id, collection, index);
                res.writeHead(200, {"content-type": "application/json"});
                res.end(`{"status":"${delete_status}"}`);
        } catch(e) {
                send_error(res, e);
        }
}

function handle_delete_element_from_embedded_objects_collection_request(req, res) {
	console.log(`received delete_element_from_collection request with path ${req.headers[":path"]}`);
	const query_object = parse(req.headers[":path"], true).query;
	if (req.method !== "POST") {
        	send_error(res, 
                        `received /oo/delete_element_from_collection/embedded with request method ${req.method}`);
		return;
	}
        const {id, collection, index} = query_object;
	if(!is_valid_uuid(id)) {
		send_error(res, `Invalid uuid.`);
		return;
	}
        if(!collection) {
                send_error(res, `Missing collection id`);
                return
        }
        let data = '';
        req.on('data', (chunk) => {
                data += chunk;
        }).on('end', () => {
                try {
                        data = JSON.parse(data);
                } catch (e) {
                        send_error(res, "Request body is not valid json."); 
                }
                try {
                        const deleted_uuid = delete_element_from_embedded_objects_collection(id, collection, index, data);
                        res.writeHead(200, {"content-type": "application/json"});
                        res.end(`{"deleted":"${deleted_uuid}"}`);
                } catch(e) {
                        send_error(res, e);
                }
        }).on('error', (e) => {
                send_error(res, 'Failed get request body');
        })
}

function handle_wrap_request(req, res) {
	console.log(`received wrap request with path ${req.headers[":path"]}`);
	const query_object = parse(req.headers[":path"], true).query;
	if (req.method !== "GET") {
        	send_error(res, `received /oo/wrap with request method ${req.method}`);
		return;
	}
        const {id, locale} = query_object;
	if(!is_valid_uuid(id)) {
		send_error(res, `Invalid uuid.`);
		return;
	}
        try {
                const object = wrap_owned_object(id, locale || "en_US");
                res.writeHead(200, {"content-type": "application/json"});
                res.end(JSON.stringify(object));
        } catch(e) {
                send_error(res, e);
        }
}
