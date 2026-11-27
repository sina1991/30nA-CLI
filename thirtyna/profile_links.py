"""Decode supported proxy share links without exposing credentials in errors."""
import base64
import json
from urllib.parse import quote, urlencode, urlunsplit


def decode64(value):
    try:
        return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True).decode()
    except (ValueError, UnicodeError) as exc:
        raise ValueError("INVALID_BASE64") from exc


def normalize(link):
    if link.startswith("vmess://"):
        try:
            data = json.loads(decode64(link[8:]))
            host = str(data["add"])
            port = int(data["port"])
            user = str(data["id"])
            if data.get("tls") not in (None, "", "none", "tls"):
                raise ValueError()
            alter_id = int(data.get("aid", 0))
            if not 1 <= port <= 65535 or alter_id < 0:
                raise ValueError()
            query = dict(type=data.get("net") or "tcp",
                         security="tls" if data.get("tls") == "tls" else "none",
                         sni=data.get("sni") or data.get("host") or host, host=data.get("host") or "",
                         path=data.get("path") or "/", aid=str(alter_id),
                         scy=data.get("scy") or "auto",
                         serviceName=data.get("path") or "",
                         headerType=(data.get("type") or "none") if data.get("net", "tcp") in ("tcp", "raw") else "none",
                         mode="multi" if data.get("type") == "multi" else "")
            if "allowInsecure" in data:
                query["allowInsecure"] = str(data["allowInsecure"]).lower()
            if data.get("alpn"):
                query["alpn"] = data["alpn"]
            if data.get("fp"):
                query["fp"] = data["fp"]
            host = "[" + host + "]" if ":" in host else host
            return urlunsplit(("vmess", quote(user, safe="") + "@" + host + ":" + str(port),
                               "", urlencode(query), quote(str(data.get("ps") or ""), safe="")))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("INVALID_VMESS_LINK") from exc
    if link.startswith("ss://") and "@" not in link.split("#", 1)[0]:
        body, separator, fragment = link[5:].partition("#")
        credentials, at, endpoint = decode64(body).rpartition("@")
        if not at:
            raise ValueError("INVALID_SS_LINK")
        return "ss://" + quote(credentials, safe="") + "@" + endpoint + (separator + fragment if separator else "")
    return link


def outbound(uri, value, stream):
    from urllib.parse import unquote
    protocol = uri.scheme
    if protocol not in ("vless", "vmess", "trojan", "ss"):
        raise ValueError("UNSUPPORTED_PROTOCOL")
    if not uri.hostname or not uri.port or not uri.username:
        raise ValueError("INVALID_LINK")
    if protocol in ("vless", "vmess"):
        user = dict(id=unquote(uri.username))
        if protocol == "vless":
            if value("encryption", "none") not in ("", "none"):
                raise ValueError("UNSUPPORTED_ENCRYPTION")
            user["encryption"] = "none"
            if value("flow"):
                user["flow"] = value("flow")
        else:
            user.update(alterId=int(value("aid", "0")), security=value("scy", "auto"))
        settings = {"vnext": [dict(address=uri.hostname, port=uri.port, users=[user])]}
    elif protocol == "trojan":
        password = unquote(uri.netloc.rsplit("@", 1)[0])
        settings = {"servers": [dict(address=uri.hostname, port=uri.port, password=password)]}
    else:
        if value("plugin"):
            raise ValueError("UNSUPPORTED_SS_PLUGIN")
        credentials = unquote(uri.netloc.rsplit("@", 1)[0])
        if ":" not in credentials:
            credentials = decode64(credentials)
        method, separator, password = credentials.partition(":")
        if not separator or not method or not password:
            raise ValueError("INVALID_SS_LINK")
        settings = {"servers": [dict(address=uri.hostname, port=uri.port,
                                     method=method, password=password)]}
        protocol = "shadowsocks"
    return dict(protocol=protocol, settings=settings, streamSettings=stream)
