#!/bin/sh
set -eu

readonly_user="${DB_READONLY_USER:-hengpintong_saas_ro}"
readonly_password="${DB_READONLY_PASSWORD:?DB_READONLY_PASSWORD is required}"
readonly_database="${DB_READONLY_NAME:-${MYSQL_DATABASE:-hengpintong_saas}}"

mysql --protocol=socket -uroot -p"$MYSQL_ROOT_PASSWORD" <<SQL
CREATE USER IF NOT EXISTS '${readonly_user}'@'%' IDENTIFIED BY '${readonly_password}';
GRANT SELECT, SHOW VIEW ON \`${readonly_database}\`.* TO '${readonly_user}'@'%';
FLUSH PRIVILEGES;
SQL
