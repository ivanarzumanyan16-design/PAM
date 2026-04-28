import {
        get_uuid_sync,
        save_uuid_sync
} from './db.mjs'


const uuids = {
        true: "b4598a37-3126-42c1-a7b2-2906b12989f8", 
        false: "df868f39-896b-431b-b699-e71b4233eaf8",
        "external_text": "3e76b8ff-9063-4052-b67a-ecd43302d269",
        "file": "37d76e87-acd6-434c-bed2-3a87d935b013",
        "vcs_item": "e1f12c03-f736-4e0a-9847-a85100903581",
        collection_kind: {
                embedded: "da952a26-e63c-49e0-a79e-c86852522ecd",
                composition: "7764d377-e113-434d-a610-8c334a57ed7c"
        },
        property_kind: {
                embedded: "ee4e31c1-25f8-4990-9872-3d77a515cb9d",
                owned: "a23dbb9f-9625-4a55-9d16-9613845ebeda"
        },
        version_control : {
                none : "8b5a3daa-556f-4e80-a41b-f78e305774db",
                full : "19a3fd43-f2f8-4b3b-9cd1-472125542004",
                only_history : "1f24af20-8cd4-437b-bdee-343cd6071274",
		automatic: "8d2ba44b-85ff-41f7-b1df-0468515ed8e4-6b4a2f25-7abc-4d94-8443-b86029f724c9"
        },
        symmetric: {
                collection: "61d68b09-2514-4d2b-baf6-ef8dcc5ce99e",
                property: "4f6620a8-8550-497c-9f9e-05c8b332c08c"
        }
}
const default_locale = "en_US";

function is_version_control_enabled(pspec) {
        return pspec.enable_version_tracking === uuids.version_control.only_history ||
                pspec.enable_version_tracking === uuids.version_control.full ||
                pspec.enable_version_tracking === uuids.version_control.automatic
}
function is_version_control_record(o) {
        return o.type === uuids.vcs_item;
}

function is_internalization_enabled(pspec) {
        return pspec.enable_internalization === uuids.true;
}

function is_embedded_collection(cspec) {
        return cspec.kind === uuids.collection_kind.embedded;
}
function is_composition_collection(cspec) {
        return cspec.kind === uuids.collection_kind.composition;
}

function is_mandatory_property(pspec) {
        return pspec.mandatory === uuids.true;
}

function has_default_value(pspec) {
        return pspec.default_value != '' &&
                pspec.default_value != undefined;
}

function is_external_property(pspec) {
        return pspec.kind === uuids.property_kind.embedded ||
               pspec.kind === uuids.property_kind.owned ||
               pspec.value_type === uuids.external_text ||
               pspec.value_type === uuids.file
}

function is_embedded_property(pspec) {
        return pspec.kind === uuids.property_kind.embedded
}

function get_propspec(type, id) {
        return type.properties.find(prop => prop.id === id);
}

function get_collspec(type, id) {
        return type.collections.find(prop => prop.id === id);
}

function get_object(uuid) {
        let o = get_uuid_sync(uuid).data;
        try {
                o = JSON.parse(o);
        } catch {
                throw `The ${uuid} is not valid JSON.`;
        }
        return o
}

function wrap_object(uuid) {
        const object = {};
        let o = get_object(uuid);
        if (!o.type || !is_valid_uuid(o.type)) {
                throw `The ${uuid} has invalid type.`
        }
        let type = get_object(o.type);
        type.properties.forEach(property => {
                object[property.id] = o[property.id];
        });
        type.collections.forEach(collection => {
                object[collection.id] = o[collection.id];
        });
        object.type = type;
        return object
}

function update_object(o) {
        if (typeof(o.type) === "object") {
                o.type = o.type.uuid;
        }
        save_uuid_sync(JSON.stringify(o), o.uuid, "application/json");
}

function get_embedded_object(o, t, c) {
        if (!c.property && !(c.collection && c.index !== undefined)) {
                throw "There is no collection or property id specified.";
        }
        let type_uuid;
        let object;
        if (c.property) {
                const propspec = get_propspec(t, c.property);  
                type_uuid = propspec.value_type;
                object = o[c.property]
        } else {
                const collspec = get_collspec(t, c.collection);  
                type_uuid = collspec.element_type;
                object = o[c.collection][c.index];
        }
        let type = get_uuid_sync(type_uuid).data;
        try {
                type = JSON.parse(type);
        } catch {
                throw `The ${type_uuid} is not valid JSON.`;
        }
        if (!c.child) {
                return [object, type]
        }
        return get_embedded_object(object, type, c.child);
}

function create_new_mani_object(type) {
        const o = {};
        const type_type = get_object(type.type);
        const name_pspec = get_propspec(type_type, "name");
        const type_name = get_property(type, name_pspec, default_locale);
        o.name = `New ${type_name}`;
        type.properties.forEach(pspec => {
                if (has_default_value(pspec)) {
                        o[pspec.id] = pspec.default_value;
                }
        });
        type.collections.forEach(cspec => {
                o[cspec.id] = [];
        });
        o["type"] = type.uuid;
        return o;
}

function get_property(o, pspec, locale, root) {
        let id = pspec.id;
        let value;
        if (is_version_control_enabled(pspec)) {
                if (is_valid_uuid(o[id])) {
			const vci = get_object(o[id]);
			if (is_version_control_record(vci)) {
                                o[id] = vci.value;
                        }
                }
        }
        if (is_internalization_enabled(pspec) && typeof o[id] === "object") {
                value = o[id][locale] || 
                        o[id][default_locale] ||
                        o[id][Object.keys(o[id])[0]];
        } else {
                value = o[id];
        }
        return value || ""
}

function set_property(o, pspec, value, locale) {
        let {id} = pspec;
        if (is_version_control_enabled(pspec)) {
                if (is_valid_uuid(o[id])) {
                        o = get_object(o[id]);
                        id = "value";
                }
        }
        if (is_internalization_enabled(pspec)) {
                if (typeof o[id] !== "object") {
                        o[id] = { [default_locale] : o[id]};
                }
                o[id][locale] = value;
        } else {
                o[id] = value;
        }
        if (is_external_property(pspec)) {
                value = set_external_property_value(o, id, value, pspec);
        }
        return value
}

function set_external_property_value(o, id, v, pspec) {
        const type = get_object(pspec.value_type);
        const value = create_new_mani_object(type);
        if (pspec.kind === uuids.property_kind.owned ||
            pspec.value_type === uuids.external_text) {
                const uuid = save_uuid_sync("{}", null, "application/json");
                value.type = type;
                value.uuid = uuid;
                update_object(value);
                o[id] = uuid;
                return uuid
        }
        o[id] = value
        return value;
}

export function get_property_in_owned_object(uuid, id, locale) {
        const object = wrap_object(uuid);
        if (id === "type") {
                return object.type.uuid
        }
        const propspec = get_propspec(object.type, id);
        if (propspec === undefined) {
                throw `There is no property with id: ${id} in object: ${uuid}.`;
        }
        return get_property(object, propspec, locale);
}

export function get_property_in_embedded_object(uuid, id, child, locale) {
        const object = wrap_object(uuid);
        const [embedded_object, type] = get_embedded_object(object, object.type, child);
        const propspec = get_propspec(type, id);
        if (propspec === undefined) {
                throw `There is no property with id: ${id}.`;
        }
        return get_property(embedded_object, propspec, locale, object);
}

export function set_property_in_owned_object(uuid, id, value, locale) {
        const o = wrap_object(uuid);
        const propspec = get_propspec(o.type, id);
        if (propspec === undefined) {
                throw `There is no property with id: ${id} in object: ${uuid}.`;
        }
        if (id === "type") {
                value = wrap_owned_object(value, true);
        }
        const r = set_property(o, propspec, value, locale);
        update_object(o);
        return r
}

export function set_property_in_embedded_object(uuid, id, value, child, locale) {
        const object = wrap_object(uuid);
        const [embedded_object, type] = get_embedded_object(object, object.type, child);
        const propspec = get_propspec(type, id);
        if (propspec === undefined) {
                throw `There is no property with id: ${id}.`;
        }
        if (id === "type") {
                value = wrap_owned_object(value, true);
        }
        const r = set_property(embedded_object, propspec, value, locale);
        update_object(object);
        return r
}

export function wrap_owned_object(uuid, locale, is_type, is_type_type) {
        const object = get_object(uuid);
        if (is_type_type === true) return object
        object.type = wrap_owned_object(object.type, locale, true, is_type);
        const type = object.type;
        get_all_properties(object, type, locale); 
        type.collections.forEach(c => {
                if (is_embedded_collection(c)) {
                        if (!object[c.id]) return
                        const eltype = get_object(c.element_type);
                        object[c.id].forEach(el => {
                                get_all_properties(el, eltype, locale, object); 
                        }); 
                }
        });
        type.properties.forEach(pspec => {
                if (is_embedded_property(pspec) && object[pspec.id]) {
                        const vt = get_object(pspec.value_type);
                        get_all_properties(object[pspec.id], vt, locale, object); 
                }
        });
        if (is_type) {
                object.type = object.type.uuid;
        }
        return object
}

function get_all_properties(object, type, locale, root) {
        type.properties.forEach(property => {
                object[property.id] = get_property(object, property, locale, root);
        });
        return object
}

export function add_element_to_collection(uuid, id, el) {
        const object = wrap_object(uuid);
        const element = wrap_object(el);  
        const cspec = get_collspec(object.type, id);
        if (cspec === undefined) {
                throw `There is no collection with id: ${id} in object: ${uuid}.`;
        }
        if (cspec.element_type !== element.type.uuid) {
                throw `The element ${el} is not of type ${cspec.element_type}.`;
        }
        object[id].push(el);
        if (cspec.symmetric) {
                add_object_in_symmetric_element(uuid, element, cspec);
                update_object(element);
        }
        update_object(object);
        return el
}

function add_object_in_symmetric_element(uuid, element, cspec) {
        if (cspec.symmetric_kind === uuids.symmetric.property) {
                element[cspec.symmetric] = uuid;
        } else {
                if (element[cspec.symmetric] &&
                    Array.isArray(element[cspec.symmetric])) {
                        element[cspec.symmetric].push(uuid);
                }
        }
}

function delete_element_in_symmetric_element(uuid, element, cspec) {
        if (cspec.symmetric_kind === uuids.symmetric.property) {
                element[cspec.symmetric] = '';
        } else {
                if (element[cspec.symmetric] &&
                     Array.isArray(element[cspec.symmetric])) {
                        const i = element[cspec.symmetric].indexOf(uuid);
                        element[cspec.symmetric].splice(i, 1);
                }
        }
}

export function delete_element_from_collection(uuid, id, el) {
        const object = wrap_object(uuid);
        const cspec = get_collspec(object.type, id);
        if (cspec === undefined) {
                throw `There is no collection with id: ${id} in object: ${uuid}.`;
        }
        const index = object[id].indexOf(el);
        if (index === -1) {
                throw `There is no element with uuid ${el} in collection ${id}.`;
        }
        object[id].splice(index, 1);
        if (is_composition_collection(cspec) && cspec.symmetric) {
                const element = wrap_object(el);
                delete_element_in_symmetric_element(uuid, element, cspec);
                update_object(element);
        }
        update_object(object);
        return el
}

export function create_element_in_collection(uuid, id) {
        const object = wrap_object(uuid);
        const cspec = get_collspec(object.type, id);
        if (cspec === undefined) {
                throw `There is no collection with id: ${id} in object: ${uuid}.`;
        }
        const type = get_object(cspec.element_type);
        const new_object = create_new_mani_object(type)
        const new_uuid = save_uuid_sync("{}", null, "application/json");
        new_object.type = type;
        new_object.uuid = new_uuid;
        update_object(new_object);
        if (object[id] === undefined) {
                object[id] = []
        }
        object[id].push(new_uuid);
        update_object(object);
        return new_uuid
}

export function create_element_in_embedded_collection(uuid, id) {
        const object = wrap_object(uuid);
        const cspec = get_collspec(object.type, id);
        if (cspec === undefined) {
                throw `There is no collection with id: ${id} in object: ${uuid}.`;
        }
        const type = get_object(cspec.element_type);
        const new_object = create_new_mani_object(type)
        if (object[id] === undefined) {
                object[id] = []
        }
        object[id].push(new_object);
        update_object(object);
        return new_object
}

export function delete_element_from_embedded_collection(uuid, id, index) {
        const object = wrap_object(uuid);
        const cspec = get_collspec(object.type, id);
        if (cspec === undefined) {
                throw `There is no collection with id: ${id} in object: ${uuid}.`;
        }
        if (object[id][index] === undefined) {
                throw `There is no element with index ${index} in colletion.`;
        }
        object[id].splice(index, 1);
        update_object(object);
        return "deleted"
}

export function create_element_in_embedded_objects_collection(uuid, id, child) {
        const object = wrap_object(uuid);
        const [embedded_object, type] = get_embedded_object(object, object.type, child);
        const cspec = get_collspec(type, id);
        if (cspec === undefined) {
                throw `There is no collection with id: ${id} in object: ${uuid}.`;
        }
        const element_type = get_object(cspec.element_type);
        const new_object = create_new_mani_object(element_type)
        embedded_object[id].push(new_object);
        update_object(object);
        return new_object
}

export function delete_element_from_embedded_objects_collection(uuid, id, index, child) {
        const object = wrap_object(uuid);
        const [embedded_object, type] = get_embedded_object(object, object.type, child);
        const cspec = get_collspec(type, id);
        if (cspec === undefined) {
                throw `There is no collection with id: ${id} in object: ${uuid}.`;
        }
        if (embedded_object[id][index] === undefined) {
                throw `There is no element with index ${index} in colletion.`;
        }
        embedded_object[id].splice(index, 1);
        update_object(object);
        return "deleted"
}

export function get_collection(uuid, id, property, locale) {
        const object = wrap_object(uuid);
        const cspec = get_collspec(object.type, id);
        if (cspec === undefined || object[cspec.id] === undefined) {
                throw `There is no collection with id: ${id} in object: ${uuid}.`;
        }
        const collection = [];
        if (!property) return object[cspec.id]
        object[cspec.id].forEach(e => {
                collection.push({
                        [property] : get_property_in_owned_object(e, property, locale),
                        uuid: e
                });
        });
        return collection
}
