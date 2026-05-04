--
-- PostgreSQL database dump
--

-- Dumped from database version 9.5.10
-- Dumped by pg_dump version 9.5.10

SET statement_timeout = 0;
SET lock_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: employees; Type: SCHEMA; Schema: -; Owner: -
--



SET search_path = public, pg_catalog;

--
-- Name: employee_gender; Type: TYPE; Schema: employees; Owner: -
--

CREATE TYPE employee_gender AS ENUM (
    'M',
    'F'
);


SET default_tablespace = '';

SET default_with_oids = false;

--
-- Name: department; Type: TABLE; Schema: employees; Owner: -
--

CREATE TABLE department (
    id character(4) NOT NULL,
    dept_name character varying(40) NOT NULL
);


--
-- Name: department_employee; Type: TABLE; Schema: employees; Owner: -
--

CREATE TABLE department_employee (
    employee_id bigint NOT NULL,
    department_id character(4) NOT NULL,
    from_date date NOT NULL,
    to_date date NOT NULL
);


--
-- Name: department_manager; Type: TABLE; Schema: employees; Owner: -
--

CREATE TABLE department_manager (
    employee_id bigint NOT NULL,
    department_id character(4) NOT NULL,
    from_date date NOT NULL,
    to_date date NOT NULL
);


--
-- Name: employee; Type: TABLE; Schema: employees; Owner: -
--

CREATE TABLE employee (
    id bigint NOT NULL,
    birth_date date NOT NULL,
    first_name character varying(14) NOT NULL,
    last_name character varying(16) NOT NULL,
    gender employee_gender NOT NULL,
    hire_date date NOT NULL
);


--
-- Name: id_employee_seq; Type: SEQUENCE; Schema: employees; Owner: -
--

CREATE SEQUENCE id_employee_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: id_employee_seq; Type: SEQUENCE OWNED BY; Schema: employees; Owner: -
--

ALTER SEQUENCE id_employee_seq OWNED BY employee.id;


--
-- Name: salary; Type: TABLE; Schema: employees; Owner: -
--

CREATE TABLE salary (
    employee_id bigint NOT NULL,
    amount bigint NOT NULL,
    from_date date NOT NULL,
    to_date date NOT NULL
);


--
-- Name: title; Type: TABLE; Schema: employees; Owner: -
--

CREATE TABLE title (
    employee_id bigint NOT NULL,
    title character varying(50) NOT NULL,
    from_date date NOT NULL,
    to_date date
);


--
-- Name: id; Type: DEFAULT; Schema: employees; Owner: -
--

-- ALTER TABLE ONLY employee ALTER COLUMN id SET DEFAULT nextval('id_employee_seq'::regclass);


--
-- Data for Name: department; Type: TABLE DATA; Schema: employees; Owner: -
--

COPY department (id, dept_name) FROM stdin;
COPY department (id, dept_name) FROM stdin;
d009	Customer Service
d005	Development
d002	Finance
d003	Human Resources
d001	Marketing
d004	Production
d006	Quality Management
d008	Research
d007	Sales
\.
COPY department_employee (employee_id, department_id, from_date, to_date) FROM stdin;
\.
COPY department_employee (employee_id, department_id, from_date, to_date) FROM stdin;
10001	d005	1986-06-26	9999-01-01
10002	d007	1996-08-03	9999-01-01
10003	d004	1995-12-03	9999-01-01
10004	d004	1986-12-01	9999-01-01
10005	d003	1989-09-12	9999-01-01
10006	d005	1990-08-05	9999-01-01
10007	d008	1989-02-10	9999-01-01
10008	d005	1998-03-11	2000-07-31
10009	d006	1985-02-18	9999-01-01
10010	d004	1996-11-24	2000-06-26
10010	d006	2000-06-26	9999-01-01
10011	d009	1990-01-22	1996-11-09
10012	d005	1992-12-18	9999-01-01
10013	d003	1985-10-20	9999-01-01
10014	d005	1993-12-29	9999-01-01
10015	d008	1992-09-19	1993-08-22
10016	d007	1998-02-11	9999-01-01
10017	d001	1993-08-03	9999-01-01
10018	d004	1992-07-29	9999-01-01
10018	d005	1987-04-03	1992-07-29
10019	d008	1999-04-30	9999-01-01
10020	d004	1997-12-30	9999-01-01
10021	d005	1988-02-10	2002-07-15
10022	d005	1999-09-03	9999-01-01
10023	d005	1999-09-27	9999-01-01
10024	d004	1998-06-14	9999-01-01
10025	d005	1987-08-17	1997-10-15
10026	d004	1995-03-20	9999-01-01
10027	d005	1995-04-02	9999-01-01
\.
COPY department_manager (employee_id, department_id, from_date, to_date) FROM stdin;
110022	d001	1985-01-01	1991-10-01
110039	d001	1991-10-01	9999-01-01
110085	d002	1985-01-01	1989-12-17
110114	d002	1989-12-17	9999-01-01
110183	d003	1985-01-01	1992-03-21
110228	d003	1992-03-21	9999-01-01
110303	d004	1985-01-01	1988-09-09
110344	d004	1988-09-09	1992-08-02
110386	d004	1992-08-02	1996-08-30
110420	d004	1996-08-30	9999-01-01
110511	d005	1985-01-01	1992-04-25
110567	d005	1992-04-25	9999-01-01
110725	d006	1985-01-01	1989-05-06
110765	d006	1989-05-06	1991-09-12
110800	d006	1991-09-12	1994-06-28
110854	d006	1994-06-28	9999-01-01
111035	d007	1985-01-01	1991-03-07
111133	d007	1991-03-07	9999-01-01
111400	d008	1985-01-01	1991-04-08
111534	d008	1991-04-08	9999-01-01
111692	d009	1985-01-01	1988-10-17
111784	d009	1988-10-17	1992-09-08
111877	d009	1992-09-08	1996-01-03
111939	d009	1996-01-03	9999-01-01
\.
COPY employee (id, birth_date, first_name, last_name, gender, hire_date) FROM stdin;
\.
COPY employee (id, birth_date, first_name, last_name, gender, hire_date) FROM stdin;
10001	1953-09-02	Georgi	Facello	M	1986-06-26
10002	1964-06-02	Bezalel	Simmel	F	1985-11-21
10003	1959-12-03	Parto	Bamford	M	1986-08-28
10004	1954-05-01	Chirstian	Koblick	M	1986-12-01
10005	1955-01-21	Kyoichi	Maliniak	M	1989-09-12
10006	1953-04-20	Anneke	Preusig	F	1989-06-02
10007	1957-05-23	Tzvetan	Zielinski	F	1989-02-10
10008	1958-02-19	Saniya	Kalloufi	M	1994-09-15
10009	1952-04-19	Sumant	Peac	F	1985-02-18
10010	1963-06-01	Duangkaew	Piveteau	F	1989-08-24
10011	1953-11-07	Mary	Sluis	F	1990-01-22
10012	1960-10-04	Patricio	Bridgland	M	1992-12-18
10013	1963-06-07	Eberhardt	Terkki	M	1985-10-20
10014	1956-02-12	Berni	Genin	M	1987-03-11
10015	1959-08-19	Guoxiang	Nooteboom	M	1987-07-02
10016	1961-05-02	Kazuhito	Cappelletti	M	1995-01-27
10017	1958-07-06	Cristinel	Bouloucos	F	1993-08-03
10018	1954-06-19	Kazuhide	Peha	F	1987-04-03
10019	1953-01-23	Lillian	Haddadi	M	1999-04-30
10020	1952-12-24	Mayuko	Warwick	M	1991-01-26
10021	1960-02-20	Ramzi	Erde	M	1988-02-10
10022	1952-07-08	Shahaf	Famili	M	1995-08-22
10023	1953-09-29	Bojan	Montemayor	F	1989-12-17
10024	1958-09-05	Suzette	Pettey	F	1997-05-19
10025	1958-10-31	Prasadram	Heyers	M	1987-08-17
10026	1953-04-03	Yongqiao	Berztiss	M	1995-03-20
\.
COPY salary (employee_id, amount, from_date, to_date) FROM stdin;
10001	60117	1986-06-26	1987-06-26
10001	62102	1987-06-26	1988-06-25
10001	66074	1988-06-25	1989-06-25
10001	66596	1989-06-25	1990-06-25
10001	66961	1990-06-25	1991-06-25
10001	71046	1991-06-25	1992-06-24
10001	74333	1992-06-24	1993-06-24
10001	75286	1993-06-24	1994-06-24
10001	75994	1994-06-24	1995-06-24
10001	76884	1995-06-24	1996-06-23
10001	80013	1996-06-23	1997-06-23
10001	81025	1997-06-23	1998-06-23
10001	81097	1998-06-23	1999-06-23
10001	84917	1999-06-23	2000-06-22
\.
COPY title (employee_id, title, from_date, to_date) FROM stdin;
10001	Senior Engineer	1986-06-26	9999-01-01
10002	Staff	1996-08-03	9999-01-01
10003	Senior Engineer	1995-12-03	9999-01-01
10004	Engineer	1986-12-01	1995-12-01
10004	Senior Engineer	1995-12-01	9999-01-01
10005	Senior Staff	1996-09-12	9999-01-01
10005	Staff	1989-09-12	1996-09-12
10006	Senior Engineer	1990-08-05	9999-01-01
10007	Senior Staff	1996-02-11	9999-01-01
10007	Staff	1989-02-10	1996-02-11
10008	Assistant Engineer	1998-03-11	2000-07-31
10009	Assistant Engineer	1985-02-18	1990-02-18
10009	Engineer	1990-02-18	1995-02-18
10009	Senior Engineer	1995-02-18	9999-01-01
10010	Engineer	1996-11-24	9999-01-01
10011	Staff	1990-01-22	1996-11-09
10012	Engineer	1992-12-18	2000-12-18
\.
