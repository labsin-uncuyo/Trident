# SPDX-FileCopyrightText: 2021 Sebastian Garcia <sebastian.garcia@agents.fel.cvut.cz>
# SPDX-License-Identifier: GPL-2.0-only
import asyncio
import json
import urllib
import requests
from typing import Union, Dict, Optional, List, Tuple
import time
import bisect
from multiprocessing import Lock

from modules.http_analyzer.set_evidence import SetEvidenceHelper
from slips_files.common.flow_classifier import FlowClassifier
from slips_files.common.parsers.config_parser import ConfigParser
from slips_files.common.slips_utils import utils
from slips_files.common.abstracts.iasync_module import AsyncModule


ESTAB = "Established"


class HTTPAnalyzer(AsyncModule):
    # Name: short name of the module. Do not use spaces
    name = "HTTP Analyzer"
    description = "Analyze HTTP flows"
    authors = ["Alya Gomaa"]

    def init(self):
        self.c1 = self.db.subscribe("new_http")
        self.c2 = self.db.subscribe("new_weird")
        self.c3 = self.db.subscribe("new_flow")
        self.channels = {
            "new_http": self.c1,
            "new_weird": self.c2,
            "new_flow": self.c3,
        }
        self.set_evidence = SetEvidenceHelper(self.db)
        self.connections_counter = {}
        self.empty_connections_threshold = 4
        # this is a list of hosts known to be resolved by malware
        # to check your internet connection
        # usually malware makes empty connections to these hosts while
        # checking for internet
        self.empty_connection_hosts = [
            "bing.com",
            "google.com",
            "yandex.com",
            "yahoo.com",
            "duckduckgo.com",
            "gmail.com",
        ]
        self.read_configuration()
        self.executable_mime_types = [
            "application/x-msdownload",
            "application/x-ms-dos-executable",
            "application/x-ms-exe",
            "application/x-exe",
            "application/x-winexe",
            "application/x-winhlp",
            "application/x-winhelp",
            "application/octet-stream",
            "application/x-dosexec",
        ]
        self.classifier = FlowClassifier()
        self.http_recognized_flows: Dict[Tuple[str, str], List[float]] = {}
        self.ts_of_last_cleanup_of_http_recognized_flows = time.time()
        self.http_recognized_flows_lock = Lock()
        self.condition = asyncio.Condition()
        # Password guessing detection: track login attempts per source IP
        self.login_attempts: Dict[str, List[Tuple[float, str]]] = {}
        # Threshold for number of login attempts to trigger password guessing alert
        self.password_guessing_threshold = 10  # Default: 10 attempts in 5 minutes
        # Common login-related paths to monitor
        self.login_paths = {
            "/login", "/signin", "/auth", "/authenticate", "/user/login",
            "/account/login", "/admin/login", "/api/login", "/api/auth",
            "/auth/login", "/sessions", "/session", "/logon", "/sign-in",
            "/wp-login.php", "/user", "/login.php", "/auth.php"
        }

    def read_configuration(self):
        conf = ConfigParser()
        self.pastebin_downloads_threshold = (
            conf.get_pastebin_download_threshold()
        )

    def detect_executable_mime_types(self, twid, flow) -> bool:
        """
        detects the type of file in the http response,
        returns true if it's an executable
        """
        if not flow.resp_mime_types:
            return False

        for mime_type in flow.resp_mime_types:
            if mime_type in self.executable_mime_types:
                self.set_evidence.executable_mime_type(twid, flow)
                return True
        return False

    def check_suspicious_user_agents(self, profileid, twid, flow):
        """Check unusual user agents and set evidence"""

        suspicious_user_agents = (
            "httpsend",
            "chm_msdn",
            "pb",
            "jndi",
            "tesseract",
        )

        for suspicious_ua in suspicious_user_agents:
            if suspicious_ua.lower() not in flow.user_agent.lower():
                continue
            self.set_evidence.suspicious_user_agent(flow, profileid, twid)
            return True
        return False

    def check_password_guessing(self, twid: str, flow) -> bool:
        """
        Detects HTTP password guessing attempts by monitoring
        repeated POST requests to login endpoints.

        Tracks login attempts per source IP and triggers an alert
        when the threshold is exceeded.

        :param twid: Time window ID
        :param flow: The HTTP flow object
        :return: True if password guessing was detected, False otherwise
        """
        # Check if this is a POST request (typically used for login)
        if not hasattr(flow, 'method') or flow.method != "POST":
            return False

        # Check if the URI path matches login endpoints
        if not hasattr(flow, 'uri') or not hasattr(flow, 'host'):
            return False

        uri_lower = flow.uri.lower()
        path = uri_lower.split('?')[0]  # Remove query string if present

        # Check if path matches any login-related paths
        is_login_path = any(
            path == login_path or
            path.startswith(login_path + '/') or
            path.endswith(login_path)
            for login_path in self.login_paths
        )

        if not is_login_path:
            return False

        # Track login attempts per source IP
        src_ip = flow.saddr
        timestamp = float(flow.starttime)
        uid = flow.uid

        # Initialize tracking for this IP if not exists
        if src_ip not in self.login_attempts:
            self.login_attempts[src_ip] = []

        # Add this attempt
        self.login_attempts[src_ip].append((timestamp, uid))

        # Remove attempts older than 5 minutes (300 seconds)
        current_time = time.time()
        cutoff_time = current_time - 300
        self.login_attempts[src_ip] = [
            (ts, uid) for ts, uid in self.login_attempts[src_ip]
            if ts > cutoff_time
        ]

        # Check if threshold exceeded
        attempts_count = len(self.login_attempts[src_ip])

        if attempts_count >= self.password_guessing_threshold:
            # Get all UIDs for the evidence
            uids = [uid for _, uid in self.login_attempts[src_ip]]
            self.set_evidence.password_guessing(twid, flow, uids, attempts_count)
            # Clear the attempts after alerting to avoid duplicate alerts
            self.login_attempts[src_ip] = []
            return True

        return False

    def check_multiple_empty_connections(self, twid: str, flow):
        """
        Detects more than 4 empty connections to
            google, bing, yandex and yahoo on port 80
        an evidence is generted only when the 4 conns have an empty uri
        """
        # to test this wget google.com:80 twice
        # wget makes multiple connections per command,
        # 1 to google.com and another one to www.google.com
        if flow.uri != "/":
            return

        if flow.dport != 80:
            return

        if not flow.resp_fuids:
            return

        if not all([fuid == "-" for fuid in flow.resp_fuids]):
            return

        # check if the host is one of the self.empty_connection_hosts
        # and get the tuple (uid, ts) of this flow
        host_to_check = None
        for host in self.empty_connection_hosts:
            if host in flow.host:
                host_to_check = host
                break

        if not host_to_check:
            return

        if host_to_check not in self.connections_counter:
            self.connections_counter[host_to_check] = []

        self.connections_counter[host_to_check].append((flow.uid, float(flow.starttime)))

        if len(self.connections_counter[host_to_check]) >= self.empty_connections_threshold:
            # get the uids of all the empty connections
            uids = [uid for uid, ts in self.connections_counter[host_to_check]]
            self.set_evidence.multiple_empty_connections(twid, flow, uids)
            self.connections_counter[host_to_check] = []
            return True

        return False

    def check_multiple_user_agents_in_a_row(
        self, flow, twid, cached_ua
    ):
        """
        Detect multiple user agents in a row from the same profileid
        """
        # all the UAs of this profileid so far
        profileid = flow.profileid
        all_ua: Dict[str, str] = self.db.get_all_user_agents(profileid)

        if not all_ua or len(all_ua) < 2:
            return False

        # we have more than 1 UA, check if we have a 'server-bag' UA
        # server-bag is a scanner UA
        if "server-bag" in all_ua:
            # our normal browser UA
            browser_ua = cached_ua
            if not browser_ua:
                return False

            # get the last 10 UAs
            recent_uas: Dict[str, str] = self.db.get_last_n_user_agents(
                profileid, 10
            )

            if not recent_uas:
                return False

            # filter out the 'server-bag' UA
            recent_uas_no_serverbag = [
                ua
                for ua in recent_uas.values()
                if ua and "server-bag" not in ua
            ]

            if len(recent_uas_no_serverbag) < 2:
                return False

            # check if the last N UAs are all the same
            if len(set(recent_uas_no_serverbag)) == 1:
                # we have a consistent browser UA with occasional server-bag UAs
                # this is not suspicious
                return False

            # we have different UAs mixed with server-bag
            self.set_evidence.multiple_user_agents(
                twid, flow, list(recent_uas.values())
            )
            return True

        return False

    def extract_info_from_ua(self, user_agent, profileid):
        """
        Extract info from user agent and store it in the db
        """
        # don't extract info from the same UA twice
        cached_ua = self.db.get_user_agent_from_profile(profileid)
        if cached_ua == user_agent:
            return

        # extract the type and version of the browser from the UA
        # self.db.store_user_agent(profileid, user_agent)
        self.db.analyze_user_agent(user_agent, profileid)

    def check_incompatible_user_agent(self, profileid, twid, flow):
        """
        Check for incompatible user agent strings
        """
        # get the last UA used by this profileid
        cached_ua = self.db.get_user_agent_from_profile(profileid)

        if not cached_ua:
            # we don't have a cached UA, store this one
            self.db.store_user_agent(profileid, flow.user_agent)
            return False

        # we have a cached UA, check if it's compatible with the current one
        # compatible means they are from the same browser family
        # ex: Chrome/90.0 and Chrome/91.0 are compatible
        # ex: Chrome/90.0 and Firefox/89.0 are not compatible

        if self.db.are_user_agents_compatible(cached_ua, flow.user_agent):
            # they are compatible, update the cached UA
            self.db.store_user_agent(profileid, flow.user_agent)
            return False

        # they are not compatible, set evidence
        self.set_evidence.incompatible_user_agent(
            profileid, twid, flow, cached_ua, flow.user_agent
        )
        # update the UA anyway
        self.db.store_user_agent(profileid, flow.user_agent)
        return True

    def get_user_agent_info(self, user_agent, profileid):
        """
        Get information about the user agent using the API
        """
        # don't query the API for the same UA twice
        cached_ua = self.db.get_user_agent_from_profile(profileid)
        if cached_ua == user_agent:
            return

        # check if the UA is in the cache
        if self.db.is_user_agent_in_cache(user_agent):
            # get the info from the cache
            ua_info = self.db.get_cached_user_agent_info(user_agent)
            if not ua_info:
                return
            self.db.store_user_agent_info(profileid, ua_info)
            return

        # not in cache, query the API
        api_url = "http://user-agents.net/api"
        try:
            # get the info from the API
            response = requests.get(api_url, params={"ua": user_agent}, timeout=5)
            if response.status_code == 200:
                ua_info = response.json()
                self.db.store_user_agent_info_in_cache(user_agent, ua_info)
                self.db.store_user_agent_info(profileid, ua_info)

        except (
            requests.exceptions.RequestException,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ):
            pass

    def check_pastebin_downloads(self, twid, flow):
        """
        Check if the user is downloading from pastebin
        """
        if "pastebin" not in flow.host:
            return False

        if not flow.resp_fuids:
            return False

        # check if any of the files downloaded are not empty
        if not all([fuid == "-" for fuid in flow.resp_fuids]):
            # get the size of the response
            if hasattr(flow, "response_body_len"):
                if (
                    flow.response_body_len
                    > self.pastebin_downloads_threshold
                ):
                    self.set_evidence.pastebin_download(twid, flow)
                    return True

        return False

    def pre_main(self):
        utils.drop_root_privs_permanently()

    async def main(self):
        if msg := self.get_msg("new_http"):
            msg = json.loads(msg["data"])
            profileid = msg["profileid"]
            twid = msg["twid"]
            flow = self.classifier.convert_to_flow_obj(msg["flow"])
            self.check_suspicious_user_agents(profileid, twid, flow)
            self.check_multiple_empty_connections(twid, flow)
            # find the UA of this profileid if we don't have it
            # get the last used ua of this profile
            cached_ua = self.db.get_user_agent_from_profile(profileid)
            if cached_ua:
                self.check_multiple_user_agents_in_a_row(
                    flow,
                    twid,
                    cached_ua,
                )

            if not cached_ua or (
                isinstance(cached_ua, dict)
                and cached_ua.get("user_agent", "") != flow.user_agent
                and "server-bag" not in flow.user_agent
            ):
                # only UAs of type dict are browser UAs,
                # skips str UAs as they are SSH clients
                self.get_user_agent_info(flow.user_agent, profileid)

            self.extract_info_from_ua(flow.user_agent, profileid)
            self.detect_executable_mime_types(twid, flow)
            self.check_incompatible_user_agent(profileid, twid, flow)
            self.check_pastebin_downloads(twid, flow)
            self.check_password_guessing(twid, flow)
            self.set_evidence.http_traffic(twid, flow)

        if msg := self.get_msg("new_weird"):
            msg = json.loads(msg["data"])
            profileid = msg["profileid"]
            twid = msg["twid"]
            weird = self.classifier.convert_to_flow_obj(msg["weird"])
            if weird.weird_type == "password_guessing":
                # Set evidence for password guessing based on weird behavior
                # Check if we already have evidence for this profileid
                if not self.db.check_evidence_exists(
                    profileid, twid, weird.weird_type
                ):
                    self.set_evidence.password_guessing_weird(
                        profileid, twid, weird
                    )

        if msg := self.get_msg("new_flow"):
            """
            Process flow recognition. This is called every time there's a
            new flow in the database
            """
            msg = json.loads(msg["data"])
            profileid = msg["profileid"]
            twid = msg["twid"]
            flow = self.classifier.convert_to_flow_obj(msg["flow"])

            # Update recognized http flows
            # Only do this for http flows
            if not hasattr(flow, "method"):
                return

            if flow.method == "GET":
                # get the tuple of (daddr, dport) to identify this connection
                # server_ip:port
                if not hasattr(flow, "dport"):
                    return
                if not hasattr(flow, "daddr"):
                    return

                # server_ip:port is a tuple that identifies the server
                server = (flow.daddr, flow.dport)

                self.http_recognized_flows_lock.acquire()
                if server not in self.http_recognized_flows:
                    self.http_recognized_flows[server] = []

                # Add the timestamp of this flow to the list
                self.http_recognized_flows[server].append(float(flow.starttime))

                # clean up old flows every 10 min
                now = time.time()
                if now - self.ts_of_last_cleanup_of_http_recognized_flows > 600:
                    # Remove flows older than 1h
                    clean_http_recognized_flows: Dict[
                        Tuple[str, str], List[float]
                    ] = {}
                    garbage = []
                    for (
                        server_ip,
                        timestamps,
                    ) in self.http_recognized_flows.items():
                        # remove timestamps older than 1h
                        timestamps = [
                            ts
                            for ts in timestamps
                            if now - float(ts) < 3600
                        ]
                        if len(timestamps) == 0:
                            garbage.append(server_ip)
                            continue

                        clean_http_recognized_flows[server_ip] = timestamps

                    for server_ip in garbage:
                        del self.http_recognized_flows[server_ip]

                    self.http_recognized_flows = (
                        clean_http_recognized_flows
                    )
                    self.ts_of_last_cleanup_of_http_recognized_flows = now

                self.http_recognized_flows_lock.release()

    async def shutdown_gracefully(self):
        """wait for all the tasks created by self.create_task()"""
        await asyncio.gather(*self.tasks, return_exceptions=True)
