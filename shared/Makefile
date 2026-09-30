# Build from application sources and requirements; never ship cached dependencies.
build-MiddlewareLayer:
	mkdir -p "$(ARTIFACTS_DIR)/certs"
	cp certs/mysql-ca.pem "$(ARTIFACTS_DIR)/certs/mysql-ca.pem"
	mkdir -p "$(ARTIFACTS_DIR)/python"
	python3 -m pip install --platform manylinux2014_x86_64 --implementation cp --python-version 3.9 --only-binary=:all: -r python/requirements.txt -t "$(ARTIFACTS_DIR)/python"
	cp python/__init__.py python/database.py python/middleware.py python/utils.py python/vehicle.py python/gate-access-dev-firebase-adminsdk-jk7hy-ebbdd45791.json "$(ARTIFACTS_DIR)/python/"
