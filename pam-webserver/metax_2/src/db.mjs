//imports from this project

//imports from standard libraries
import {
		createReadStream
	,	createWriteStream
	,	readFileSync
	,	writeFileSync
	,	existsSync
	,	mkdirSync
	,	statSync
	,	unlinkSync
} from "fs";
import { randomUUID } from "crypto";

//imports from thrid-party libraries

const open_files = {};

export function initialize_db() {
	assert(config.storage !== undefined, "storage path is not specified.");
	if(!existsSync(config.storage)) {
		try {
			mkdirSync(config.storage);
			if(config.storage[config.storage.length -1] !== "/") {
				config.storage += "/";
			}
		} catch(e) {
			if(e.code === "EACCES") {
				console.error("unable to create storage directory, permission denied.");
			} else if(e.code === "ENOENT") {
				console.error("unable to create storage directory, invalid path.")
			}
			process.exit(-1);
		}
	}
	console.log("db initialized");
}

export function get_uuid(uuid, start_byte, end_byte, chunking = true) {
	if(!is_valid_uuid(uuid)) throw "invalid uuid";
	const contract = get_contract_file(uuid);
	assert(contract.mime !== undefined, "Missing mime type in contract in get_uuid.");
	const response = {
		mime: contract.mime,
		length: get_data_length(uuid)
	}
	if(chunking && contract.mime.split("/")[0] === "video" ||
		contract.mime.split("/")[0] === "audio") {
		response.type = "partial";
		//const chunk_size = Math.floor(response.length / 200);
		const chunk_size = 2000000; 
		end_byte = end_byte || Math.min(start_byte + chunk_size, response.length - 1);
		response.end_byte = end_byte;
		response.data_stream = read_file_stream(uuid, start_byte, end_byte);
	} else {
		response.type = "full";
		response.data_stream = read_file_stream(uuid);
	}
	return response;
}

export function get_uuid_sync(uuid, start_byte) {
	if(!is_valid_uuid(uuid)) throw "invalid uuid";
	const contract = get_contract_file(uuid);
	assert(contract.mime !== undefined, "Missing mime type in contract in get_uuid.");
	const data = read_file(uuid);
	return {
		mime: contract.mime,
		data: data
	};
}

export function save_uuid(data_stream, mime, type, uuid) {
	return new Promise(async (res, rej) => {
		if(is_valid_uuid(uuid)) {
			const contract = get_contract_file(uuid);
			if(contract.mime !== mime) {
				set_contract_file(uuid, mime);
			}
		} else {
			uuid = `${randomUUID()}-${randomUUID()}`;
			set_contract_file(uuid, mime);
		}
                try {
                        if (type === "node") {
                                const write_stream = await write_file_stream(uuid);
                                data_stream.pipe(write_stream);
                                write_stream.on("finish", () => {
                                        res(uuid);
                                });
                        } else if (type === "data") {
                                await write_form_data_stream(data_stream, uuid, res, rej);
                        }
                } catch(e) {
                        rej("Can't save uuid");
                        return
                }
	})
}

export function save_uuid_sync(data, uuid, mime) {
	if(is_valid_uuid(uuid)) {
		const contract = get_contract_file(uuid);
		if(contract.mime !== mime) {
			set_contract_file(uuid, mime);
		}
	} else {
		uuid = `${randomUUID()}-${randomUUID()}`;
		set_contract_file(uuid, mime);
	}
	assert(is_valid_uuid(uuid), "save_uuid_sync invalid uuid");
	assert(data !== undefined, "save_uuid_sync recerived empty data");
	try { 
		writeFileSync(config.storage + uuid, data);
		return uuid;
	} catch (err) {
		throw new Error("faild save uuid sync");	
	}
	
}

export function delete_uuid(uuid) {
	get_contract_file(uuid);
	delete_file(uuid + ".contract");
	delete_file(uuid);
}

function get_contract_file(uuid) {
	assert(is_valid_uuid(uuid), "get_contract_file received invalid uuid");
	const contract_blob = read_file(`${uuid}.contract`);
	let contract;
	try {
		contract = JSON.parse(contract_blob);
	} catch(e) {
		throw new Error("Unable to parse contract file");
	}
	if(contract.mime === undefined) {
		throw new Error(`Mime type missing in contract file of ${uuid}`);
	}
	return contract;
}

function set_contract_file(uuid, mime) {
	assert(is_valid_uuid(uuid), "set_contract_file received invalid uuid");
	const contract = {"path": `storage/${uuid}`, "mime": mime};
	write_file(`${uuid}.contract`, JSON.stringify(contract));
}

function get_data_length(f) {
	try {
		assert(f !== undefined, "get_file_stat didn't receive any argument");
		return statSync(config.storage + f).size;
	} catch(e) {
		throw new Error("failed to get uuid stat.");
	}
}

function read_file(f) {
	assert(f !== undefined, "read_file didn't receive any argument");
	try {
		return readFileSync(config.storage + f);
	} catch(e) {
		console.log(`Failed to read_file ${f}, error code: `, e.code);
		throw new Error(`${f} not found.`);
	}
}

function write_file(f, b) {
	try {
		assert(f !== undefined, "write_file didn't receive file path.");
		assert(b !== undefined, "write_file didn't receive file body.");
		return writeFileSync(config.storage + f, b);
	} catch(e) {
		console.log(`Failed to write_file ${f}, error code: `, e.code);
		throw new Error(`unable to save in ${f}`);
	}
}

function read_file_stream(f, start, end) {
	try {
		assert(f !== undefined, "read_file_stream didn't receive any argument");
		if(start === undefined || end === undefined) {
			return createReadStream(config.storage + f);
		} else {
			return createReadStream(config.storage + f, {start, end});
		}
	} catch(e) {
		console.log(`failed to get file ${f}, error code: `, e.code);
		throw new Error(`Unable to read uuid ${uuid}`);
	}
}

function write_file_stream(f) {
        assert(f !== undefined, "write_file_stream didn't receive any argument");
        return new Promise((res, rej) => {
                if (!open_files[f]) {
                        const write_stream = create_write_file_stream(f);
                        res(write_stream);
                        return
                }
                open_files[f].on("close", () => {
                        if (open_files[f] !== undefined) {
                                console.error("file already opened for writing");
                                rej();
                        }
                        const write_stream = create_write_file_stream(f);
                        res(write_stream);
                })
        })
}

function create_write_file_stream(f) {
	try {
                const write_stream = createWriteStream(config.storage + f);
                open_files[f] = write_stream;
                write_stream.on("close", () => {
                        delete open_files[f];
                })
                return write_stream
        } catch(e) {
		throw new Error(`failed to save ${f}`);
        }
}

async function write_form_data_stream(data_stream, uuid, res, rej) {
	let is_first_chunk = true;
	let separator = '';
	let body = "";
	let write_stream = await write_file_stream(uuid);
	data_stream.on('data', (chunk) => {
		if (is_first_chunk) {
			let i = chunk.indexOf("\n");
			separator = chunk.slice(0, i-1);
			chunk = chunk.slice(i+1);
			for (let j=0; j<3; j++) {
				i = chunk.indexOf("\n");
				chunk = chunk.slice(i+1);
			}
			is_first_chunk = false;
		}
		const separator_index = chunk.indexOf("\r\n" + separator);
		if (separator_index !== -1) {
			chunk = chunk.slice(0, separator_index);
		}
		write_stream.write(chunk);
	}).on('end', () => {
		write_stream.close();
		res(uuid);
	}).on('error', (err) => {
		rej("failed to save");
	});
}

function delete_file(f) {
	try {
		assert(f !== undefined, "delete_file didn't receive any argument");
		unlinkSync(config.storage + f);
		return {"status": "success"};
	} catch(e) {
		throw new Error("failed delete file");
	}
}
