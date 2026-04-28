import { connect } from "http2";

let session = 0;

const exit = (e) => {
	console.log("Test Failed: ", e);
	process.exit(-1);
}

async function test_create_element_in_collection(uuid, cid) {
        console.log("Testing create element in collection...");
	return new Promise((resolve, reject) => {
		const get_request = session.request({
			":path": `/oo/create_element_in_collection?id=${uuid}&collection=${cid}`,
			":method": "GET",
		})
		let data = "";
		get_request
			.on("data", c => data += c)
			.on("end", () => {
				try {
					const res = JSON.parse(data);
					if("uuid" in res) {
						console.log("Created element: ", res);
						resolve(res.uuid)
					} else {
						exit(res);
					}
				} catch(e) {
					exit(e);
				}
			}).on("error", (e) => {
                                exit(e);
                        })
	});
}

async function test_delete_element_from_collection(uuid, cid, el) {
        console.log("Testing delete element from collection...");
	return new Promise((resolve, reject) => {
		const get_request = session.request({
			":path": `/oo/delete_element_from_collection?id=${uuid}&collection=${cid}&element=${el}`,
			":method": "GET",
		})
		let data = "";
		get_request
			.on("data", c => data += c)
			.on("end", () => {
				try {
					const res = JSON.parse(data);
					if("deleted" in res) {
						console.log("Deleted element: ", res);
						resolve(res.deleted)
					} else {
						exit(res);
					}
				} catch(e) {
					exit(e);
				}
			}).on("error", (e) => {
                                exit(e);
                        })
	});
}

async function test_add_element_to_collection(uuid, cid, el) {
        console.log("Testing add element to collection...");
	return new Promise((resolve, reject) => {
		const get_request = session.request({
			":path": `/oo/add_element_to_collection?id=${uuid}&collection=${cid}&element=${el}`,
			":method": "GET",
		})
		let data = "";
		get_request
			.on("data", c => data += c)
			.on("end", () => {
				try {
					const res = JSON.parse(data);
					if("uuid" in res) {
						console.log("Added element: ", res);
						resolve(res.uuid);
					} else {
						exit(res);
					}
				} catch(e) {
					exit(e);
				}
			}).on("error", (e) => {
                                exit(e);
                        })
	});
}

async function test_create_element_in_embedded_collection(uuid, cid) {
        console.log("Testing create element in embedded collection...");
	return new Promise((resolve, reject) => {
		const get_request = session.request({
			":path": `/oo/create_element_in_embedded_collection?id=${uuid}&collection=${cid}`,
			":method": "GET",
		})
		let data = "";
		get_request
			.on("data", c => data += c)
			.on("end", () => {
				try {
					const res = JSON.parse(data);
                                        if ("error" in res) {
						exit(res);
                                        } else {
						console.log("Status: " + res.status);
						resolve();
                                        }
				} catch(e) {
					exit(e);
				}
			}).on("error", (e) => {
                                exit(e);
                        })
	});
}

async function test_delete_element_from_embedded_collection(uuid, cid, index) {
        console.log("Testing delete element from embedded collection...");
	return new Promise((resolve, reject) => {
		const get_request = session.request({
			":path": `/oo/delete_element_from_embedded_collection?id=${uuid}&collection=${cid}&index=${index}`,
			":method": "GET",
		})
		let data = "";
		get_request
			.on("data", c => data += c)
			.on("end", () => {
				try {
					const res = JSON.parse(data);
                                        if ("error" in res) {
						exit(res);
                                        } else {
						console.log("Status: " + res.status);
						resolve();
                                        }
				} catch(e) {
					exit(e);
				}
			}).on("error", (e) => {
                                exit(e);
                        })
	});
}

async function test_set_property(uuid, pid, value, locale) {
        console.log("Testing set property...");
	return new Promise((resolve, reject) => {
		const post_request = session.request({
			":path": `/oo/set_property?id=${uuid}&property=${pid}${locale ? "&locale=" + locale : ""}`,
			":method": "POST",
                        "content-type": "text/plain"
		})
                post_request.write(value);
                post_request.end();
		let data = "";
		post_request
			.on("data", c => data += c)
			.on("end", () => {
				try {
					const res = JSON.parse(data);
                                        if ("error" in res) {
						exit(res);
                                        } else {
						console.log(res);
						resolve();
                                        }
				} catch(e) {
					exit(e);
				}
			}).on("error", (e) => {
                                exit(e);
                        })
	});
}

async function test_get_property(uuid, pid, locale) {
        console.log("Testing get property...");
	return new Promise((resolve, reject) => {
		const get_request = session.request({
			":path": `/oo/get_property?id=${uuid}&property=${pid}${locale ? "&locale=" + locale : ""}`,
			":method": "GET",
		})
		let data = "";
		get_request
			.on("data", c => data += c)
			.on("end", () => {
				try {
					const res = JSON.parse(data);
                                        if ("error" in res) {
						exit(res);
                                        } else {
						console.log("Property value: " + res.value);
						resolve(res.value);
                                        }
				} catch(e) {
					exit(e);
				}
			}).on("error", (e) => {
                                exit(e);
                        })
	});
}

async function test_wrap(uuid, locale) {
        console.log("Testing wrap...");
	return new Promise((resolve, reject) => {
		const get_request = session.request({
			":path": `/oo/wrap?id=${uuid}${locale ? "&locale=" + locale : ""}`,
			":method": "GET",
		})
		let data = "";
		get_request
			.on("data", c => data += c)
			.on("end", () => {
				try {
					const res = JSON.parse(data);
                                        if ("error" in res) {
						exit(res);
                                        } else {
                                                console.log("Wrap passed");
						//console.log(res);
						resolve(res);
                                        }
				} catch(e) {
					exit(e);
				}
			}).on("error", (e) => {
                                exit(e);
                        })
	});
}

async function test_set_property_embedded_object(uuid, pid, body, locale) {
        console.log("Testing set property in embedded object...");
	return new Promise((resolve, reject) => {
		const post_request = session.request({
			":path": `/oo/set_property/embedded?id=${uuid}&property=${pid}${locale ? "&locale=" + locale : ""}`,
			":method": "POST",
                        "content-type": "text/plain"
		})
                post_request.write(body);
                post_request.end();
		let data = "";
		post_request
			.on("data", c => data += c)
			.on("end", () => {
				try {
					const res = JSON.parse(data);
                                        if ("error" in res) {
						exit(res);
                                        } else {
						console.log(res);
						resolve();
                                        }
				} catch(e) {
					exit(e);
				}
			}).on("error", (e) => {
                                exit(e);
                        })
	});
}

async function test_get_property_embedded_object(uuid, pid, body, locale) {
        console.log("Testing get property in embedded object...");
	return new Promise((resolve, reject) => {
		const post_request = session.request({
			":path": `/oo/get_property/embedded?id=${uuid}&property=${pid}${locale ? "&locale=" + locale : ""}`,
			":method": "POST",
                        "content-type": "text/plain"
		})
                post_request.write(body);
                post_request.end();
		let data = "";
		post_request
			.on("data", c => data += c)
			.on("end", () => {
				try {
					const res = JSON.parse(data);
                                        if ("error" in res) {
						exit(res);
                                        } else {
						console.log(res);
						resolve();
                                        }
				} catch(e) {
					exit(e);
				}
			}).on("error", (e) => {
                                exit(e);
                        })
	});
}

async function test_wrap_embedded(uuid, body, locale) {
        console.log("Testing wrap embedded object...");
	return new Promise((resolve, reject) => {
		const post_request = session.request({
			":path": `/oo/wrap/embedded?id=${uuid}${locale ? "&locale=" + locale : ""}`,
			":method": "POST",
                        "content-type": "text/plain"
		})
                post_request.write(body);
                post_request.end();
		let data = "";
		post_request
			.on("data", c => data += c)
			.on("end", () => {
				try {
					const res = JSON.parse(data);
                                        if ("error" in res) {
						exit(res);
                                        } else {
						console.log("Wrap embedded object passed");
						resolve();
                                        }
				} catch(e) {
					exit(e);
				}
			}).on("error", (e) => {
                                exit(e);
                        })
	});
}


async function main() {
        const maniUUID = "aea62f74-9622-4c9c-93cf-dcd707e11e43";
	session = connect('https://herbals.am:8001');
	session.on("connect", async () => {
                const uuid = await test_create_element_in_collection(maniUUID, "types");
                await test_delete_element_from_collection(maniUUID, "types", uuid);
                await test_add_element_to_collection(maniUUID, "types", uuid);
                await test_create_element_in_embedded_collection(uuid, "properties");
                await test_set_property(uuid, 'name', "Test name", "en_US");
                await test_set_property(uuid, 'name', "Փորձնական", "hy_AM");
                await test_get_property(uuid, 'name', "hy_AM");
                await test_get_property(uuid, 'name');
                await test_wrap(uuid, "hy_AM");
                await test_wrap(uuid);
                await test_set_property_embedded_object(uuid, "name", JSON.stringify({"value" : "Test embedded name", child: { collection: "properties", index: 0}}), "en_US");
                await test_get_property_embedded_object(uuid, "name", JSON.stringify({ collection: "properties", index: 0}), "en_US");
                await test_wrap_embedded(uuid, JSON.stringify({ collection: "properties", index: 0}));
                // test create/delete element to/from collection in embedded objects
                await test_delete_element_from_embedded_collection(uuid, "properties", 0);
                await test_delete_element_from_collection(maniUUID, "types", uuid);
		console.log("tests passed successfully.")
		session.close();
	})
	session.on('error', (err) => console.error(err, "error from http2"))
}

main();
