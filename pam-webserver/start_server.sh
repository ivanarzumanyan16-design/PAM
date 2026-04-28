#!/bin/bash

#setting environment variable for self-signed certificate ignorance
#NOTE THIS LINE NEEDS TO BE DELETED IN RELEASE MODE
export NODE_TLS_REJECT_UNAUTHORIZED=0

source ./start.conf

#start metax
pushd ./metax_2/
npm start storage=../storage/ port=$METAX_PORT key=$SELF_PRIVKEY cert=$SELF_CERT > ../logs/metax/$current_datetime.log &
popd

sleep 2 # wait metax starting

#start greenhosting webserver
pushd /opt/PAM/pam-webserver/greenhosting_webserver_2/
npm start host_metax=localhost:$METAX_PORT key=$LE_PRIVKEY cert=$LE_CERT sitemap_uuid=$SITEMAP_UUID read_server_port=$READ_PORT write_server_port=$WRITE_PORT > ../logs/webserver/$current_datetime.log
popd
