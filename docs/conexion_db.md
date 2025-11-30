## Conectarse a la base de datos desde el cliente (labuser)

Sigue estos pasos desde la máquina comprometida (`labuser`) para comprobar la base de datos remota en `172.31.0.10`.

1) Conectarse al cliente comprometido

```bash
ssh labuser@127.31.0.10 -p 2223
```

Contraseña: adminadmin

2) (Opcional) Verificar que `psql` está instalado:

```bash
which psql || echo "psql no está instalado"
```

3) Conectar y ejecutar consultas rápidas a PostgreSQL (host: `172.31.0.10`, puerto: `5432`)

Listar tablas del esquema `public`:

```bash
psql -h 172.31.0.10 -p 5432 -U postgres -d labdb -c "\dt"
```

Contar registros en la tabla `employee`:

```bash
psql -h 172.31.0.10 -p 5432 -U postgres -d labdb -c "SELECT COUNT(*) FROM employee;"
```

Ver algunos registros de ejemplo:

```bash
psql -h 172.31.0.10 -p 5432 -U postgres -d labdb -c "SELECT * FROM employee LIMIT 5;"
```

Notas:
- Si `psql` no está disponible en el cliente, puedes ejecutar los comandos por SSH en el servidor:

```bash
ssh root@172.31.0.10 "psql -U postgres -d labdb -c '\\dt'"
```

- La conexión por password dependerá de la configuración del servidor; en este laboratorio el usuario `postgres` suele usar autenticación `trust` o no requiere contraseña desde la red interna.

Si quieres, puedo añadir ejemplos para conectarte como `john_scott` una vez creado:

```bash
psql -h 172.31.0.10 -p 5432 -U john_scott -d labdb -W
# password: john_scott
```
