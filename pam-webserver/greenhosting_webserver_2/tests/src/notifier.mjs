//imports from this project

//imports from standard libraries
import { parse } from "url";
import { randomUUID} from "crypto";
import { connect } from "http2";

//imports from third party libraries
import nodemailer from "nodemailer"

const trace = (m) => logger.trace("notifier", m);
const warning = (m) => logger.warning("notifier", m);
const error = (m) => logger.error("notifier", m);

const get_name_property_hy = (u) => http_get(`/oo/get_property?id=${u}&property=name&locale=hy_AM`)
					.then(r => JSON.parse(r))
					.then(r => r.value);

export async function init_notifier_transporters() {
	for(let i = 0; i < sitemap.websites.length; i++) {
		let p = await construct_transporter_package(i);
		if(p === 0) {
			trace(`${sitemap.websites[i].name} doesn't have mailing credentials, skipping`);
		} else {
			sitemap.websites[i].mail_transporter
						= nodemailer.createTransport(p);
			trace(`added transported for ${sitemap.websites[i].name}`);
		}
	}
}

export async function notify_update(uuid, cert, headers) {
	try {
		trace("start notify_update for uuid: " + uuid);
		const authority = headers[":authority"];
		const referer = headers["referer"];
		const u_i = await get_user_sitemap_indices(cert, authority);
		if(sitemap.websites[u_i["website_index"]].mail_transporter === undefined) {
			warning("received notify, but mail transporter is not registered");
			return;
		}
		const obj = await get_mani_user_object(uuid)
		const t = await sitemap.websites[u_i["website_index"]].mail_transporter;
		const username = await get_user_name_from_sitemap(u_i);
		const user_mail = sitemap.websites[u_i["website_index"]]
						["mail_notifier"]["user"];
		const m_p = await construct_mailing_package(obj, user_mail,
							username, referer);
		if(m_p["to"].length > 0) {
			await send_mail(t, m_p);
		} else {
			trace("notify_update received notify command with no watchers, uuid: " + uuid)
		}
		trace("END notify_update for uuid: " + uuid);
	} catch (e) {
		error("failed to notify users, " + e);
		trace("END notify_update for uuid: " + uuid);
	}
}

async function get_mani_user_object(uuid) {
	trace("get_mani_user_object");
	const obj = await metax_get(uuid)
		.then(r => JSON.parse(r))
		.catch(e => {
			trace("END get_mani_user_object");
			throw new Error("notify_update received non-json data: " + uuid);
		});
	if(obj
		&& is_valid_uuid(obj["type"])
		&& is_valid_uuid(obj["uuid"])
		&& Array.isArray(obj["watchers"])) {
		trace("END get_mani_user_object");
		return obj;
	} else {
		trace("END get_mani_user_object");
		throw new Error("notify_update received invalid object for notifying");
	}
}

async function construct_transporter_package(w) {
	trace("construct_transporter_package");
	let s = sitemap.websites[w];
	if(s 
		&& s["mail_notifier"]
		&& s["mail_notifier"]["host"]
		&& s["mail_notifier"]["port"]
		&& s["mail_notifier"]["user"]
		&& s["mail_notifier"]["password"]) {
		trace("END construct_transporter_package");
		return {
			host: s["mail_notifier"]["host"],
			port: +s["mail_notifier"]["port"],
			secure: true,
			auth: {
				user: s["mail_notifier"]["user"],
				pass: s["mail_notifier"]["password"]
			}
		}
	} else {
		trace("END construct_transporter_package");
		return 0;
	}
}

async function construct_mailing_package(obj, from, u, referer) {
	trace("construct_mailing_package")
	const tname = await get_name_property_hy(obj["type"]);
	const objname = await get_name_property_hy(obj["uuid"]);
	const to = await get_watcher_mails(obj);
	const subject = `Թարմացում: [${tname}] ${objname}`;
	const html = `<p>Խմբագրող։ ${u}</p><p>Թարմացումը կարող էք տեսնել <a href="${referer}#${obj["uuid"]}">այստեղ</a></p>`
	trace("END construct_mailing_package")
	return { from, to, subject, html };
}

async function get_user_name_from_sitemap(index) {
	trace("get_user_name_from_sitemap");
	const user_id = sitemap.websites[index.website_index]
				.client_certificates[index.cert_index].user_id;
	let user = await metax_get(user_id)
			.then(r => JSON.parse(r));
	if(user && is_valid_uuid(user["type"])) {
		//tmp solution, getting first account name
		//if accounts array has elements, first element will be selected
		if(Array.isArray(user["accounts"]) && user["accounts"].length > 0) {
			trace("END get_user_name_from_sitemap");
			return await get_name_property_hy(user["accounts"][0]);
		} else {
			trace("END get_user_name_from_sitemap");
			return await get_name_property_hy(user_id);
		}
	} else {
		trace("END get_user_name_from_sitemap");
		throw new Error("invalid user in sitemap, uuid: " + user_id);
	}
}

async function get_watcher_mails(obj) {
	trace("get_watcher_mails");
	const mail_regexp = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
	let mails = [];
	for(let i = 0; i < obj["watchers"].length; i++) {
		let recepient = await metax_get(obj["watchers"][i])
			.then(r => JSON.parse(r));
		if(mail_regexp.test(recepient["email"])) {
			mails.push(recepient["email"]);
		} else {
			warning("notify_update: recepient " + 
				recepient["uuid"] + " doesn't have a valid mail, skipping");
		}
	}
	trace("END get_watcher_mails");
	return mails;
}

async function send_mail(transporter, m) {
	trace("send_mail");
	const info = await transporter.sendMail(m)
		.catch(e => {
			error("failed to send mail: " + e);
		});
	trace("END send_mail");
}

async function get_user_sitemap_indices(cert, authority) {
	trace("get_user_sitemap_indices");
	let i = sitemap.websites.findIndex(website => {
		let index = website.subdomains.findIndex(el => el.name === authority.split(":")[0])
		return index !== -1;
	});
	if(i !== -1) {
		let client_key = cert.raw.toString('base64');
		let j = sitemap.websites[i].client_certificates.findIndex(el =>
			el["certificate"]
			.replace(/[\r\n]/gm, '')
			.replace(/[\n]/gm, '')
			.includes(client_key));
		if(j !== -1) {
			trace("END get_user_sitemap_indices");
			return { website_index: i, cert_index: j }
		} else {
			trace("END get_user_sitemap_indices");
			throw new Error("unable to find user.");
		}
	} else {
		trace("END get_user_sitemap_indices");
		throw new Error("unable to find user.");
	}
}
