FROM postgres:16-alpine

# Optional init SQL scripts placed in db/init will run on first boot.
COPY init/ /docker-entrypoint-initdb.d/
