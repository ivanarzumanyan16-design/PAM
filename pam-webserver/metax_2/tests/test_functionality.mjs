import { connect } from "http2";
import  WebSocket from "ws";
import {readFileSync} from "fs";

let client_token = "";
let session = 0;

const exit = (e) => {
	console.log("Test Failed: ", e);
	process.exit(-1);
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

function handle_new_message(m) {
	try {
		m = JSON.parse(m);
		if("event" in m) {
			switch(m["event"]) {
				case "connected":
					handle_connected_event(m);
					break;
				case "update":
					handle_update_event(m);
					break;
			}
		} else {
			console.log("error occurred, received message with no event", m);
			process.exit(-1);
		}
	} catch(e) {
		console.log("error", e);
	}
}

function handle_connected_event({token}) {
	if(token === undefined) {
		console.log("received connect event with no token, exiting...");
		process.exit(-1);
	} else {
		client_token = token;
		console.log("websocket succesfully connected, token:", token);
	}
}

function handle_update_event({uuid}) {
	if(uuid === undefined) {
		console.log("handle_update_message did not receive uuid");
	} else {
		console.log("websocket received update message for uuid:", uuid);
	}
}

async function save_data(d) {
	return new Promise((resolve, reject) => {
		const save_request = session.request({
			":path": "/db/save/node",
			":method": "POST",
			"content-type": "text/plain"})
		save_request.write(d);
		save_request.end();
		let data = "";
		save_request
			.on("data", c => data += c)
			.on("end", () => {
				try {
					console.log("esiminch", data, "received data")
					const res = JSON.parse(data);
					if("uuid" in res) {
						console.log("save response: ", res);
						resolve(res.uuid)
					} else {
						exit(res);
					}
				} catch(e) {
					exit(e);
				}
			})
	});
}

async function get_data(uuid) {
	return new Promise((resolve, reject) => {
		const get_request = session.request({
			":path": `/db/get?id=${uuid}`,
			":method": "GET"
		})
		let data = "";
		get_request
			.on("data", c => data += c)
			.on("end", () => {
				console.log("get response: ", data);
				resolve();

			})
			.on("error", console.log)
	});
}

async function update_data(uuid, d) {
	return new Promise((resolve, reject) => {
		const update_request = session.request({
			":path": `/db/save/node?id=${uuid}`,
			":method": "POST",
			"content-type": "text/plain"
		})
		update_request.write(d);
		update_request.end();
		let data = "";
		update_request
			.on("data", c => data += c)
			.on("end", () => {
				try {
					const res = JSON.parse(data);
					if("uuid" in res) {
						console.log("update response: ", res);
						resolve(res.uuid)
					} else {
						exit(res);
					}
				} catch(e) {
					exit(e);
				}
			})
	});
}

async function delete_data(uuid) {
	return new Promise((resolve, reject) => {
		const delete_request = session.request({
			":path": `/db/delete?id=${uuid}`,
			":method": "GET",
			"content-type": "text/plain"
		})
		let data = "";
		delete_request
			.on("data", c => data += c)
			.on("end", () => {
				try {
					const res = JSON.parse(data);
					if("uuid" in res) {
						console.log("delete response: ", res);
						resolve(res.uuid)
					} else {
						exit(res);
					}
				} catch(e) {
					exit(e);
				}
			})
	});
}

async function register_listener(uuid) {
	return new Promise((resolve, reject) => {
		const get_request = session.request({
			":path": `/db/register_listener?id=${uuid}&token=${client_token}`,
			":method": "GET"
		})
		let data = "";
		get_request
			.on("data", c => data += c)
			.on("end", () => {
				console.log(data);
				resolve();
			})
			.on("error", console.log)
	});
}

async function unregister_listener(uuid) {
	return new Promise((resolve, reject) => {
		const get_request = session.request({
			":path": `/db/unregister_listener?id=${uuid}&token=${client_token}`,
			":method": "GET"
		})
		let data = "";
		get_request
			.on("data", c => data += c)
			.on("end", () => {
				console.log(JSON.parse(data));
				resolve();
			})
			.on("error", console.log)
	});
}

async function main() {
	session = connect('https://realschool.am:7001',
		{
			"key": readFileSync("./bagrat_darbinyan/private_key.pem"),
			"cert": readFileSync("./bagrat_darbinyan/bagrat_darbinyan_certificate.pem"),
			"passphrase": "evtlVnnEMb"
		});
	session.on("connect", async () => {
		const ws_client = new WebSocket("wss://realschool.am:7001");
		ws_client.on("message", handle_new_message);
		await sleep(500);
		const uuid = await save_data("initial save.");
		await register_listener(uuid);
		await get_data(uuid);
		console.log(uuid)
		await update_data(uuid, "updating the data.");
		await unregister_listener(uuid);
		await get_data(uuid);
	//	await delete_data(uuid);
		console.log("tests passed successfully.")
		session.close();
	})
	session.on('error', (err) => console.error(err, "error from http2"))
}

main();

