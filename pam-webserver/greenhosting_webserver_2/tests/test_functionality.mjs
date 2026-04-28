import { connect } from "http2";

let session = 0;

const exit = (e) => {
	console.log("Test Failed: ", e);
	process.exit(-1);
}

async function save_data(d) {
	return new Promise((resolve, reject) => {
		const save_request = session.request({
			":path": "/db/save/node",
			":method": "POST",
			"content-type": "text/plain"
		})
		save_request.write(d);
		save_request.end();
		let data = "";
		save_request
			.on("data", c => data += c)
			.on("end", () => {
				try {
					console.log(data, "received data")
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

async function main() {
	session = connect('https://herbals.am:8001');
	session.on("connect", async () => {
		const uuid = await save_data("initial save.");
		await get_data(uuid);
		console.log(uuid)
		await update_data(uuid, "updating the data.");
		await get_data(uuid);
		await delete_data(uuid);
		console.log("tests passed successfully.")
		session.close();
	})
	session.on('error', (err) => console.error(err, "error from http2"))
}

main();

