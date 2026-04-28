//imports from standard libraries
import https from 'https'

const API_URL_HOST = "api.openai.com";
const API_URL_PATH = "/v1/chat/completions";
const API_MODEL = "gpt-4o";
const API_TEMPERATURE = 0.3
const GPT_SYSTEM_INSTRUCTION = "You are a powerful translator of modern and ancient languages. You aren't using transliterated or foreign words."

export async function translate_property(id, property, locale, api_key) {
        const object = await metax_get(id).then(JSON.parse).catch(e => {
                throw "invalid object"
        });
        if (!object[property] || typeof object[property] !== "object") {
                throw "no such property or it's not translatable " + property
        }
        const langs = [];
        for (let l of Object.keys(object[property])) {
                if (l === locale || !object[property][l]) continue
                langs.push({
                        locale: l,
                        value: object[property][l]
                });
        }
        if (langs.length === 0) {
                throw "can't translate property, no value available"
        }
        const messages = construct_messages(object, property, locale, langs);
        const data = await openai_api_request(messages, api_key);
        return data
}

function construct_messages(object, property, locale, langs) {
        // TODO: Add some context
        const messages = [{role: "system", content: GPT_SYSTEM_INSTRUCTION}];
        let prompt = `Translate text from `
        langs.forEach(l => {
                prompt += `${l.locale} : "${l.value}" `;
        });
        prompt += `to ${locale}.`;
        prompt += " Please provide only translated text without quotes.";
        messages.push({role: "user", content: prompt});
        return messages
}

function openai_api_request(messages, api_key) {
        return new Promise((res, rej) => {
                let data = '';
                const body = {
                        model: API_MODEL,
                        temperature: API_TEMPERATURE,
                        messages: messages
                }
                const request = https.request({
                        hostname: API_URL_HOST,
                        path: API_URL_PATH,
                        method: "POST",
                        headers: {
                                "Content-Type": "application/json",
                                "Authorization": `Bearer ${api_key}`
                        }
                }, (r) => {
                        r.on("data", d => {
                                data += d;
                        })
                        r.on("error", e => {
                                error("error in openai request " + e);
                                rej(e);
                        })
                        r.on("end", () => {
                                try {
                                        data = JSON.parse(data);
                                        res(data.choices[0].message.content);
                                } catch(e) {
                                        error("Invalid response from openai " +
                                                        data.toString());
                                        rej("invalid response");
                                }
                        })
                });
                request.write(JSON.stringify(body));
                request.end();
        })
}
