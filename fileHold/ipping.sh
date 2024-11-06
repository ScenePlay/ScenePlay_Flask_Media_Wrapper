#!/bin/bash
renice -n 19 -p $$


DB_PATH="ip_results.db"
check_socket() {
    local host=$1
    local port=$2
    nc -z -w1 $host $port &> /dev/null
    if [ $? -eq 0 ]; then
        echo -n ", $port"
    fi
}

ping_host() {
    local host=$1
    ping -c 1 $host &> /dev/null
    if [ $? -eq 0 ]; then
        local hostname=$(getent hosts $host | awk '{ print $2 }')
        hostname=${hostname:-""}

        local ports=""
        for port in 22 80 443 8080 8081 8082 8083 8084 8085 8086 8087 8088; do
            ports+=$(check_socket $host $port)
        done
        ports=$(echo $ports | sed 's/^, //')

        if [ -n "$ports" ]; then
            echo "$host $ports $hostname"
            save_to_db "$host" "$ports" "$hostname"
        fi
    fi
}


save_to_db() {
    local host=$1
    local ports=$2
    local hostname=$3

    sqlite3 $DB_PATH <<EOF
CREATE TABLE IF NOT EXISTS ip_results (
    id INTEGER PRIMARY KEY,
    ip TEXT UNIQUE,
    ports TEXT,
    hostname TEXT,
    last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO ip_results (ip, ports, hostname)
VALUES ('$host', '$ports', '$hostname')
ON CONFLICT(ip) DO UPDATE SET
ports=excluded.ports,
hostname=excluded.hostname,
last_checked=CURRENT_TIMESTAMP;
EOF
}

main() {
    local ip_base=$(echo $1 | cut -d. -f1-3)
    local start=$(echo $1 | cut -d. -f4)
    local end=$((16 + start - 1))

    for ((i=start; i<=end; i++)); do
        if ((i > 0 && i < 255)); then
            #echo "$ip_base.$i"
            ping_host "$ip_base.$i"
        fi
    done
}

if [ $# -eq 0 ]; then
    echo "Usage: $0 <IP base>"
    exit 1
fi

main $1