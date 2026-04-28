mkdir ../certs
cd ../certs
openssl genpkey -algorithm RSA -out metax.key
openssl req -x509 -new -key metax.key -out metax.crt -days 1000
