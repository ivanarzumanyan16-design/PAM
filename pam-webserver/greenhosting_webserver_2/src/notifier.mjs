//imports from third party libraries
import nodemailer from "nodemailer"

const trace = (m) => logger.trace("notifier", m);
const warning = (m) => logger.warning("notifier", m);
const error = (m) => logger.error("notifier", m);

const get_property = (u, id, l="hy_AM") => http_get(`/oo/get_property?id=${u}&property=${id}&locale=${l}`)
					.then(r => JSON.parse(r))
					.then(r => r.value);
const notify_map = {};
const notify_timeout = 300000;

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

export async function add_notifier(uuid, cert, body, headers) {
        const parent_uuid = await get_property(uuid, "parent").catch(e => "");
        const notify_uuid = parent_uuid || uuid;
	if (notify_map[notify_uuid] === undefined) {
		notify_map[notify_uuid] = {changes:[]}
	} else {
		clearTimeout(notify_map[notify_uuid].timeout)
	}
        if (parent_uuid) {
                body.child_uuid = uuid;
        }
        if (body.type === "property") {
                const i = notify_map[notify_uuid].changes.findIndex(c => c.id === body.id);
                if (i !== -1) {
                        body.old = notify_map[notify_uuid].changes[i].old 
                        notify_map[notify_uuid].changes.splice(i, 1);
                }
        }
	notify_map[notify_uuid].changes.push(body)
	notify_map[notify_uuid].timeout = setTimeout(async () => {
                await notify_update(notify_uuid, cert, notify_map[notify_uuid].changes, headers);
		delete notify_map[notify_uuid]
	}, notify_timeout)
}

async function notify_update(uuid, cert, changes, headers) {
        try {
                const { locale="hy_AM" } = changes[0];
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
                const username = await get_user_name_from_sitemap(u_i, locale);
                const user_mail = sitemap.websites[u_i["website_index"]]
                                                ["mail_notifier"]["user"];
                const m_p = await construct_mailing_package(obj, user_mail,
                                                        username, referer, changes);
                if(m_p["to"].length > 0) {
                        await send_mail(t, m_p);
                } else {
                        trace("notify_update received notify command with no watchers, uuid: " + uuid)
                }
                trace("END notify_update for uuid: " + uuid);
        } catch(e) {
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

async function construct_mailing_package(obj, from, u, referer, changes) {
	trace("construct_mailing_package")
        const { locale = "hy_AM" } = changes[0];
	const tname = await get_property(obj["type"], "name", locale);
	const objname = await get_property(obj["uuid"], "name", locale);
	const to = await get_watcher_mails(obj);
	const subject = `Թարմացում: [${tname}] ${objname}`;
        let html = `<table style="border:1px solid black; border-collapse:collapse">`;
        const type = await metax_get(obj.type).then(r => JSON.parse(r));
        for(let p of type.properties) {
                if (p.id === "uuid" ) continue
                let v = await get_property(obj.uuid, p.id, locale)
                if (is_valid_uuid(v)) {
                        v = await get_property(v, "name", locale) + "*";
                }
                html += `<tr><th style="border:1px solid black;text-align:left;padding:5px">
                        ${p.name[locale] || Object.values(p.name)[0]}</th>
                        <td style="border:1px solid black;padding:5px">${v}</td></tr>`;
        }
	html += `</table><p>Խմբագրող՝ ${u}</p>
	 <p>Փոփոխութիւններ՝ </p>`
	for (let change of changes) {
                if (change.child_uuid !== undefined) {
                        const child_type_uuid = await get_property(change.child_uuid, "type");
                        const child_type = await metax_get(child_type_uuid).then(r => JSON.parse(r));
                        html += `Փոփոխուել է ${await get_property(child_type_uuid, "name", locale)}` +
                                ` ( Անուն՝ ${await get_property(change.child_uuid, "name", locale)} )՝ ` +
                                await construct_change_html(change.child_uuid, child_type, change, locale);
                } else {
                        html += await construct_change_html(obj.uuid, type, change, locale);
                }
	}
        const date = new Date();
	html += `<p>Ժամ՝ ${("0" + date.getHours()).slice(-2)}:${("0" + date.getMinutes()).slice(-2)}</p>`
        html += `<p>Թարմացումը կարող էք տեսնել <a href="${referer}#${obj["uuid"]}">այստեղ</a></p>`
	trace("END construct_mailing_package")
	return { from, to, subject, html };
}

async function construct_change_html(uuid, type, change, locale) {
        if (change.type === "property") {
                const p = type.properties.find(p => p.id === change.id)
                if (p === undefined) {
                        throw new Error("no such property in object " + id)
                }
                let new_value = await get_property(uuid, p.id, locale);
                let old_value = change.old;
                if (is_valid_uuid(new_value)) {
                        new_value = await get_property(new_value, "name", locale) + "*";
                } 
                if (is_valid_uuid(change.old)) {
                        old_value = await get_property(change.old, "name", locale) + "*";
                } else {
                        old_value = typeof change.old === "object" ? 
                                change.old[locale] || "" : change.old || "";
                }
                return `<p>&emsp;<b>${p.name[locale] || Object.values(p.name)[0]}՝ </b>
                                        <span style="color:red">${old_value}</span> => 
                                        <span style="color:green">${new_value}</span></p>`;
        } else {
                const c = type.collections.find(c => c.id === change.id)
                if (c === undefined) {
                        throw new Error("no such collection in object " + id)
                }
                const type_name = await get_property(c.element_type, "name", locale);
                if (change.type === "collection_add") {
                        return `<p>&emsp;Աւելացուել է նոր ${type_name}։</p>`
                } else if (change.type === "collection_delete") {
                        return `<p>&emsp;Ջնջուել է ${type_name}:</p>`
                } else {
                        throw new Error("unknown change")
                }
        }

}

async function get_user_name_from_sitemap(index, locale) {
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
			return await get_property(user["accounts"][0], "name", locale);
		} else {
			trace("END get_user_name_from_sitemap");
			return await get_property(user_id, "name", locale);
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
