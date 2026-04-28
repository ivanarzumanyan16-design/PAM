//imports from standard libraries
import {  createReadStream
	, createWriteStream
	, statSync
	, unlinkSync
	, renameSync } from "fs";
import { pipeline } from "stream";
import { createGzip } from "zlib";

const notDefinedYet = 0;

/** The logger singleton object */
let logger = notDefinedYet;

const wait = (delay, resolveValue) => new Promise((resolve) => {
  setTimeout(() => resolve(resolveValue), delay);
});

class Logger {
        constructor() { 
                console.assert( logger === notDefinedYet,
                        'Trying to create second instance of class Logger');
        	this.file_channel = { usage: false };
		this.console_channel = { usage: false };
		this.pattern = "%p %Y-%m-%d %H:%M:%S.%i %s: %t";
		this.log_size = 0;
		this.tmp_file_log = "";
		this.is_rotating = false;
	}

	/*  
	  *  @summary configures logger class with given config.
          *  @param {String} config - config object
	 */
	configure = (config) => {
		const success_res = {"status": "success"};
		if(config.console_channel.usage === true) {
			this.console_channel = config.console_channel;
		}
		if(config.pattern !== undefined){
			this.pattern = config.pattern;
		}
		if( config.file_channel.usage === true){
			this.file_channel = config.file_channel;
			if(this.file_channel.path === undefined) {
				return {"status": "error",
					"message": "file channel is enabled, but path not specified"};
			}
			if(this.file_channel.rotation === undefined) {
				this.file_channel.rotation = 50;
			}
			this.file_channel.rotation *= 1024**2;
			return new Promise((res, rej) => {
				this.file_channel.stream = createWriteStream(this.file_channel.path,
					{ 'flags': 'a' , 'encoding': "utf8"});
				this.file_channel.stream.on("open",() => {
					this.change_log_size(
						(statSync(this.file_channel.path).size))
					res(success_res)
				});
				this.file_channel.stream.on("error",
					(e) => res({ "status": "error",
						"message": this.handle_file_channel_error(e)}))
			})
			
		}
		return success_res;
	};

	/* private method */
	handle_file_channel_error = (e) => {
		switch(e.code) {
			case "EACCES":
				return "Unable to initialize file logger, permission denied.";
			case "ENOENT":
				return "Unable to initialize file logger, no such directory.";
			default:
				return e.message;
		}
	} 

	/* private method */
	write_in_file_channel = (payload) => {
		if(this.file_channel.usage) {
			if(!this.is_rotating) {
				this.file_channel.stream.write(`${payload}`)
				this.change_log_size(payload.length);
			} else {
				this.tmp_file_log += payload;
			}
		}
	
	}
	
	/*  
	  *  @summary logs warning message.
          *  @param {String} module - module of the project where log is called.
          *  @param {String} message - log message. 
	 */
	warning = (module, message) => {
		let payload = this.construct_log("Warning", module, message);
		this.write_in_file_channel(payload);
		if(this.console_channel.usage) console.warn(payload)
	}
	
	
	/*
	  *  @summary logs error message.
          *  @param {String} module - module of the project where log is called.
          *  @param {String} message - log message. 
	 */
	error = (module, message) => {
		let payload = this.construct_log("Error", module, message);
		this.write_in_file_channel(payload);
		if(this.console_channel.usage) console.error(payload)
	}

	/*  
	  *  @summary logs trace message.
          *  @param {String} module - module of the project where log is called.
          *  @param {String} message - log message. 
	 */
	trace = (module, message) => {
		let payload = this.construct_log("Trace", module, message);
		this.write_in_file_channel(payload);
		if(this.console_channel.usage) console.log(payload)
	}

	/*  
	  *  @summary logs info message.
          *  @param {String} module - module of the project where log is called.
          *  @param {String} message - log message. 
	 */
	info  = (module, message) => {
		let payload = this.construct_log("Info", module, message);
		this.write_in_file_channel(payload);
		if(this.console_channel.usage) console.log(payload)
	}

	/* private method */
	change_log_size = (s) => {
		this.log_size += s;
		if(this.log_size >= this.file_channel.rotation){
			this.rotate_log_file();
		}
	}

	/* private method */
	archive_log_file = () => {
		createReadStream(`${this.file_channel.path}.tmp`)
			.pipe(createGzip())
			.pipe(createWriteStream(
				`${this.file_channel.path}_${Date.now()}.gz`))
			.on("finish", () => 
				unlinkSync(`${this.file_channel.path}.tmp`)
			)
	}

	/* private method */
	rotate_log_file = async () => {
		if(this.is_rotating) return;
		this.is_rotating = true;
		this.file_channel.stream.close(() => {
			this.log_size = 0;
			renameSync(this.file_channel.path, `${this.file_channel.path}.tmp`);
			this.archive_log_file();
			this.file_channel.stream = createWriteStream(
				this.file_channel.path,
				{ 'flags': 'a' , 'encoding': "utf8"});
			this.file_channel.stream.on("open",() => {
				this.file_channel.stream.write(this.tmp_file_log);
				this.is_rotating = false;
				this.change_log_size(this.tmp_file_log.length);
				this.tmp_file_log = "";
			});
		})
	}

	/* private method */
	construct_log = (t, mod, mes) => {
		const date = new Date();
		let payload = this.pattern;
		payload = payload.replace("%p", t);
		payload = payload.replace("%Y", date.getFullYear());
		payload = payload.replace("%m", date.getMonth() + 1);
		payload = payload.replace("%d", date.getDate());
		payload = payload.replace("%H", date.getHours());
		payload = payload.replace("%M", date.getMinutes());
		payload = payload.replace("%S", date.getSeconds());
		payload = payload.replace("%i", date.getMilliseconds());
		payload = payload.replace("%s", mod);
		payload = payload.replace("%t", mes);
		return payload + '\n' 
	}

}

logger = new Logger();

export default logger;
