//imports from this project
import logger from "./logger.mjs";
import {
	 	 handle_new_write_server_stream
	,	 handle_new_read_only_stream
	,	 handle_metax_update_message
	,	 handle_new_client_session
	,	 handle_websocket_new_connection
} from "./router.mjs";
import { init_notifier_transporters } from "./notifier.mjs";

//imports from standard libraries
import { 
		createSecureServer
	,	connect
} from "http2";
import { readFileSync, createWriteStream } from "fs";
import { createSecureContext } from "tls";

//imports from third party libraries
import { WebSocketServer, WebSocket } from "ws";

process.on('uncaughtException', (err, origin) => {
	console.log(Date.now(), "Uncaught exception", err, origin);
})

const config = {};
const logger_options = {
	file_channel: {
		usage: false,
		rotation: 10,
		path: "/opt/metax_storage/logs/metax.log"
	},
	console_channel: { usage: true },
	pattern: "%p %Y-%m-%d %H:%M:%S.%i %s: %t"
};

const website_uuids = [];
global.sitemap = {};
global.config = config;
global.assert = (c, m) => {
	if(!c) {
		error("Assertion violation: " + m);
		process.exit(-1);
	}
}

global.is_valid_uuid = (u) => {
	return /^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$/i.test(u) ||
		/^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}-[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$/i.test(u);
}

global.http_get = (path) => {
	return new Promise((resolve, reject) => {
		const get_request = metax.request({
			":path": path,
			":method": "GET"
		})
		let data = "";
		let is_error = false;
		get_request
			.on("response", headers => {
				if(headers[":status"] === 400) {
					is_error = true;
				}
			})
			.on("data", c => data += c)
			.on("end", () => {
				if(is_error) {
					reject(data);
				} else {
					resolve(data);
				}
			})
			.on("error", reject);
	});
}
global.logger = logger;
global.metax = 0;
global.metax_wss_token = "";
global.metax_get = (u) => http_get(`/db/get?id=${u}`);
global.metax_register_listener = (u, t) => http_get(`/db/register_listener?id=${u}&token=${metax_wss_token}`);
global.metax_unregister_listener = (u, t) => http_get(`/db/unregister_listener?id=${u}&token=${metax_wss_token}`);

const trace = (m) => logger.trace("webserver", m);
const warning = (m) => logger.warning("webserver", m);
const error = (m) => logger.error("webserver", m);

global.sessions_log = createWriteStream("./sessions.log",
	{ 'flags': 'a' , 'encoding': "utf8"});

main();

async function main() {
	const log = await logger.configure(logger_options);
	if(log.status === "success") {
		trace("logger configured.");
		configure_webserver();
		await connect_to_host_metax();
		await connect_to_host_metax_websocket();
		await init_sitemap();
		await init_notifier_transporters();
		start_read_only_server(config.read_server_port);
		start_write_server(config.write_server_port);
	} else {
		console.log("logger error: ", log.message);
		process.exit(-1);
	}
}

function connect_to_host_metax() {
	return new Promise((resolve, reject) => {
		trace("connecting to host metax.");
		metax = connect(`https://${config.host_metax}`);
		metax.on("error", e => {
			error('failed to connect to host metax: ' + e);
			process.exit(-1);
		});
		metax.on("connect", () => {
			trace("successfully connected to host metax.");
			resolve("success")
		});
	})
}
//TODO implement website adding dynamically
async function handle_sitemap_uuid_update() {
	trace("handle_sitemap_uuid_update");
	/*
	const updated_sitemap = await metax_get(config.sitemap_uuid)
							.then(JSON.parse);
	for(let i = 0; i < updated_sitemap.websites.length; i++) {
		if (website_uuids.indexOf(updated_sitemap.websites[i]) === -1) {
			warning("adding new website with uuid: " + updated_sitemap.websites[i]);
			const new_website = await get_website(updated_sitemap.websites[i]);
			sitemap.websites.push(new_website);
		}
	}
	*/
	trace("END handle_sitemap_uuid_update");
}

async function handle_website_uuid_update(w_uuid) {
	trace("handle_website_uuid_update for " + w_uuid);
	let i = sitemap.websites.findIndex(el => el.uuid === w_uuid);
	assert(i !== -1, "received website update for uuid which is not found in sitemap.");
	try {
		sitemap.websites[i] = await get_website(w_uuid);
	} catch(e) {
		error(e);
	}
	trace("END handle_website_uuid_update for " + w_uuid);
}

function connect_to_host_metax_websocket() {
	return new Promise((resolve, reject) => {
		const metax_wss = new WebSocket(`wss://${config.host_metax}`);
		metax_wss.on("error", error);
		metax_wss.on("open", () => trace("connected to metax websocket."));
		metax_wss.on("message", (m) => {
			try {
				m = JSON.parse(m);
				if(m.event === "connected") {
					metax_wss_token = m.token;
					resolve();
				} else if(m.event === "update") {
					if(is_valid_uuid(m.uuid)) {
						if(m.uuid === config.sitemap_uuid) {
							handle_sitemap_uuid_update();
						}
						if(website_uuids.indexOf(m.uuid) !== -1) {
							handle_website_uuid_update(m.uuid);
						}
						handle_metax_update_message(m.uuid);
					} else {
						error("received update message with invalid uuid.");
					}
				}
			} catch(e) {
				error("unable to parse websocket message from metax:", e);
				reject();
			}
		});
	});
}

function configure_webserver() {
	trace("configure_webserver");
	const argv = process.argv.slice(2);
	for(let i = 0; i < argv.length; i++) {
		let pairs = argv[i].split("=");
		config[pairs[0]] = pairs[1];
	}
	assert(config.host_metax !== undefined, "host metax is not defined.");
	assert(is_valid_uuid(config.sitemap_uuid), "sitemap_uuid is not a valid uuid.");
	assert(config.key !== undefined, "private key path is not defined.");
	assert(config.cert !== undefined, "certificate path is not defined.");
	assert(config.write_server_port !== undefined, "write server port is not defined.");
	assert(config.read_server_port !== undefined, "read server port is not defined.");
	trace("END configure_webserver");
}

function start_read_only_server(port) {
	assert(!isNaN(port), "port must be a number.");
	trace("starting read-only server");
	const http_server = createSecureServer({
		peerMaxConcurrentStreams: 1500,
		maxSessionMemory: 1000,
		SNICallback: sni_callback_read_only,
		key: readFileSync(config.key),
		cert: readFileSync(config.cert),
		allowHTTP1: true
	});
	http_server.on("session", handle_new_client_session);
	http_server.on("stream", handle_new_read_only_stream);
	http_server.on("error", handle_http_server_error);
	http_server.listen(port,
		() => trace(`read-only server running on port: ${port}`));
	const wss = new WebSocketServer({ server: http_server });
	wss.on("connection", handle_websocket_new_connection);
}

function start_write_server(port) {
	assert(!isNaN(port), "port must be a number.");
	trace("starting write server");
	const http_server = createSecureServer({
		peerMaxConcurrentStreams: 1500,
		maxSessionMemory: 1000,
		SNICallback: sni_callback,
		key: readFileSync(config.key),
		cert: readFileSync(config.cert),
		allowHTTP1: true,
		requestCert: true,
		rejectUnauthorized: true
	});
	http_server.on("stream", handle_new_write_server_stream);
	http_server.on("session", handle_new_client_session);
	http_server.on("error", handle_http_server_error);
	http_server.listen(port,
		() => trace(`write server running on port: ${port}`));
	const wss = new WebSocketServer({ server: http_server });
	wss.on("connection", handle_websocket_new_connection);
}

function handle_http_server_error(e, port) {
	switch(e.code) {
		case "EADDRINUSE":
			console.error(`the port ${port} is already in use`);
			process.exit(-1);
			break;
	}
}

async function init_sitemap() {
	sitemap = await metax_get(config.sitemap_uuid)
			.then(r => JSON.parse(r))
			.catch(e => {
				error("unable to get sitemap uuid: " + e);
				process.exit(-1);
			});
	await metax_register_listener(config.sitemap_uuid);
	for(let i = 0; i < sitemap.websites.length; i++) {
		sitemap.websites[i] = await get_website(sitemap.websites[i]);
	}
}

async function get_website(website_uuid) {
	trace(`get_website for ${website_uuid}`)
	const website = await metax_get(website_uuid)
			.then(r => JSON.parse(r))
			.catch(e => {
				error("unable to get website uuid: " + e);
				process.exit(-1);
			});
	let is_default = false;
	await metax_get(website.ssl_private_key.file)
		.then(r => website.ssl_private_key = r)
		.catch(e => {
			is_default = true;
			error(`unable to get private key for ${website.name}, defaulting`);
			website.ssl_private_key = null;
		})
	if(is_default) {
		website.ssl_certificate = null;
	} else {
		await metax_get(website.ssl_certificate.file)
			.then(r => website.ssl_certificate = r)
			.catch(e => {
				error(`unable to get ssl certificate for ${website.name}, defaulting`);
				website.ssl_certificate = null;
				website.ssl_private_key = null; 
			})
	}
	for(let i = 0; i < website.client_certificates.length; i++) {
		let ca = website.client_certificates[i];
		await metax_get(ca.certificate.file)
			.then(r => website.client_certificates[i].certificate = r)
			.catch(e => {
				error(`unable to get ssl certificate for ${ca.name}, skipping`);
			})
	}
	if(website_uuids.indexOf(website_uuid) === -1) {
		website_uuids.push(website_uuid);
		await metax_register_listener(website_uuid)
	}
	trace(`END get_website for ${website_uuid}`)
	return website;
}

function sni_callback_read_only(serverName, cb) {
        let cert = null
        let key = null
        let ca = "";
	let i = sitemap.websites.findIndex(website => {
		let index = website.subdomains.findIndex(el => el.name === serverName)
		if(index !== -1) {
			return website;
		}
	})
	if(i !== -1){
		key = sitemap.websites[i].ssl_private_key;
		cert = sitemap.websites[i].ssl_certificate;
		for(let j = 0; j < sitemap.websites[i].client_certificates.length; j++) {
			ca += sitemap.websites[i].client_certificates[j]["certificate"];
		}
	}else if(cert === null && key === null){
		key = readFileSync(config.key);
		cert = readFileSync(config.cert);
	}
        cb(null, new createSecureContext({
                cert,
                key,
                ca
        }));
}

function sni_callback(serverName, cb) {
        let cert = null
        let key = null
        let ca = "";
	let i = sitemap.websites.findIndex(website => {
		let index = website.subdomains.findIndex(el => el.name === serverName)
		if(index !== -1) {
			return website;
		}
	})
	if(i !== -1){
		key = sitemap.websites[i].ssl_private_key;
		cert = sitemap.websites[i].ssl_certificate;
		for(let j = 0; j < sitemap.websites[i].client_certificates.length; j++) {
			ca += sitemap.websites[i].client_certificates[j]["certificate"];
		}
	}else if(cert === null && key === null){
		key = readFileSync(config.key);
		cert = readFileSync(config.cert);
	}
	trace("trying new secure connection " + serverName);
        cb(null, new createSecureContext({
                cert,
                key,
                ca
        }));
}
