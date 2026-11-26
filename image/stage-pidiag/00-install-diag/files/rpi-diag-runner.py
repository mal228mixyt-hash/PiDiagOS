#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PiDiagOS Hardware Verification & Reporting Engine.

Boards: Raspberry Pi 3 (BCM2837), Pi 4 (BCM2711), Pi 5 (BCM2712),
including CM3/CM3+/CM4/CM4S/CM5, Pi 400, Pi 500/500+.

Runs at each boot via rpi-diag.service.
Reports: /boot/firmware/diag_results/*.json|*.html, with copies to removable USB.
"""

import argparse
import html
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime

RESULTS_DIR_BOOT = "/boot/firmware/diag_results"
BOOT_MOUNT = "/boot/firmware"
USB_MOUNT = "/mnt/usb_diag_export"
WEB_PORT = 8080
DEFAULT_STRESS_SECONDS = 60
MIN_RAM_MB = 900
STRESS_FAIL_TEMP_C = 85.0
STRESS_WARN_TEMP_C = 80.0
# get_throttled bits describing the current state: 0 = undervoltage,
# 2 = active throttling. Cumulative bits 16 and 18 are excluded: they remain
# set after any event since boot.
THROTTLE_ACTIVE_BITS = 0x5
EXT5V_MIN_V = 4.80
EXT5V_MAX_V = 5.35
LOCK_PATH = "/run/pidiag.lock"

# Fields of the 32-bit revision code: NOQuuuWuFMMMCCCCPPPPTTTTTTTTRRRR
RAM_MAP_MB = {0: 256, 1: 512, 2: 1024, 3: 2048, 4: 4096, 5: 8192, 6: 16384}
SOC_MAP = {0: "BCM2835", 1: "BCM2836", 2: "BCM2837", 3: "BCM2711", 4: "BCM2712"}
MFG_MAP = {0: "Sony UK", 1: "Egoman", 2: "Embest", 3: "Sony Japan", 4: "Embest", 5: "Stadium"}
BOARD_TYPE_MAP = {
    0x04: "Pi 2B", 0x08: "Pi 3B", 0x0a: "CM3", 0x0d: "Pi 3B+", 0x0e: "Pi 3A+",
    0x10: "CM3+", 0x11: "Pi 4B", 0x12: "Pi Zero 2 W", 0x13: "Pi 400",
    0x14: "CM4", 0x15: "CM4S", 0x17: "Pi 5", 0x18: "CM5",
    0x19: "Pi 500/500+", 0x1a: "CM5 Lite", 0x1b: "CM0",
}
THROTTLE_BITS = {
    0: ("0x1", "CRITICAL", "Undervoltage detected (current undervoltage)"),
    1: ("0x2", "WARNING", "Arm frequency capped (current ARM frequency limit)"),
    2: ("0x4", "CRITICAL", "Currently throttled (active throttling)"),
    3: ("0x8", "WARNING", "Soft temperature limit active (temperature threshold reached)"),
    16: ("0x10000", "WARNING", "Undervoltage has occurred (since boot)"),
    17: ("0x20000", "INFO", "Arm frequency capping has occurred"),
    18: ("0x40000", "WARNING", "Throttling has occurred (since boot)"),
    19: ("0x80000", "INFO", "Soft temperature limit has occurred"),
}
# Unassigned pins on the 40-pin header. Do not touch ID_SD/ID_SC,
# UART, I2C, or SPI: HAT EEPROMs or other peripherals may be connected.
SAFE_TEST_GPIOS = [4, 5, 6, 12, 13, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27]

PIN_LEVEL_RE = re.compile(r"\|\s*(hi|lo)\b")
PMIC_RAIL_RE = re.compile(r"^\s*(\S+)\s+(?:volt|current)\(\d+\)=([0-9.]+)([AV])\s*$")


# --------------------------------------------------------------------------
# General helpers
# --------------------------------------------------------------------------

def read_text(path, default=""):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def run(cmd, timeout=30):
    """Run a command without a shell. Returns (rc, stdout, stderr)."""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except FileNotFoundError:
        return 127, "", "%s: not found" % cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "", "timeout after %ss" % timeout
    except OSError as exc:
        return 126, "", str(exc)


def vcgencmd(*args, **kwargs):
    return run(["vcgencmd"] + list(args), timeout=kwargs.get("timeout", 15))


def parse_float(text):
    m = re.search(r"-?\d+(?:\.\d+)?", text or "")
    return float(m.group(0)) if m else None


def now_stamp():
    return datetime.now().astimezone()


# --------------------------------------------------------------------------
# LED indicators
# --------------------------------------------------------------------------

def _led_write(led_dir, name, value):
    path = os.path.join(led_dir, name)
    try:
        with open(path, "w") as f:
            f.write(str(value))
    except OSError:
        pass


def set_led_state(mode):
    """ACT/PWR: heartbeat during tests, both on for PASS, ACT off for FAIL."""
    act_dir = "/sys/class/leds/ACT"
    pwr_dir = "/sys/class/leds/PWR"

    if mode == "TESTING":
        _led_write(act_dir, "trigger", "heartbeat")
        return

    if mode == "PASS":
        for d in (act_dir, pwr_dir):
            _led_write(d, "trigger", "none")
            _led_write(d, "brightness", 1)
        return

    if mode == "FAIL":
        _led_write(act_dir, "trigger", "none")
        _led_write(act_dir, "brightness", 0)
        _led_write(pwr_dir, "trigger", "heartbeat")


# --------------------------------------------------------------------------
# 1. Board identification and RAM authenticity check
# --------------------------------------------------------------------------

def decode_revision(rev_int):
    return {
        "new_style": bool((rev_int >> 23) & 0x1),
        "ram_mb": RAM_MAP_MB.get((rev_int >> 20) & 0x7, 0),
        "ram_code": (rev_int >> 20) & 0x7,
        "manufacturer": MFG_MAP.get((rev_int >> 16) & 0xF, "Unknown"),
        "mfg_code": (rev_int >> 16) & 0xF,
        "soc": SOC_MAP.get((rev_int >> 12) & 0xF, "Unknown"),
        "soc_id": (rev_int >> 12) & 0xF,
        "soc_code": (rev_int >> 12) & 0xF,
        "board_type": BOARD_TYPE_MAP.get((rev_int >> 4) & 0xFF, "Unknown"),
        "board_type_code": (rev_int >> 4) & 0xFF,
        "pcb_revision": "1.%d" % (rev_int & 0xF),
        "warranty_void": bool((rev_int >> 25) & 0x1),
    }


def test_identity_and_ram():
    cpuinfo = read_text("/proc/cpuinfo")
    rev_hex = re.search(r"^Revision\s*:\s*([0-9a-fA-F]+)", cpuinfo, re.M)
    serial = re.search(r"^Serial\s*:\s*([0-9a-fA-F]+)", cpuinfo, re.M)
    rev_hex = rev_hex.group(1) if rev_hex else "0000"
    serial = serial.group(1) if serial else "0000000000000000"

    model_dt = read_text("/sys/firmware/devicetree/base/model").strip("\x00\n ")
    rev_int = int(rev_hex, 16)
    decoded = decode_revision(rev_int)

    # Detected RAM: firmware first, then MemTotal.
    rc, out, _ = vcgencmd("get_config", "total_mem")
    m = re.search(r"total_mem=(\d+)", out)
    if rc == 0 and m and int(m.group(1)) > 0:
        detected_ram_mb = int(m.group(1))
        ram_source = "vcgencmd get_config total_mem"
    else:
        mem_kb = re.search(r"MemTotal:\s+(\d+)\s+kB", read_text("/proc/meminfo"))
        detected_ram_mb = round(int(mem_kb.group(1)) / 1024) if mem_kb else 0
        ram_source = "/proc/meminfo MemTotal"

    expected_ram_mb = decoded["ram_mb"]
    # MemTotal is always below nominal capacity due to reserved regions; allow 15%.
    ram_match_ok = bool(expected_ram_mb) and abs(detected_ram_mb - expected_ram_mb) <= expected_ram_mb * 0.15
    min_ram_ok = detected_ram_mb >= MIN_RAM_MB

    status = "PASS" if (ram_match_ok and min_ram_ok and not decoded["warranty_void"]) else "FAIL"

    return {
        "status": status,
        "model_dt": model_dt or "Unknown",
        "serial": serial,
        "revision_hex": "0x" + rev_hex,
        "decoded": dict(decoded,
                        factory_ram_mb=expected_ram_mb,
                        detected_ram_mb=detected_ram_mb,
                        ram_source=ram_source,
                        ram_authenticity_ok=ram_match_ok,
                        meets_minimum_ram=min_ram_ok),
    }


# --------------------------------------------------------------------------
# 2. Power, throttling, PMIC
# --------------------------------------------------------------------------

def parse_throttled():
    rc, out, _ = vcgencmd("get_throttled")
    m = re.search(r"0x([0-9a-fA-F]+)", out)
    value = int(m.group(1), 16) if (rc == 0 and m) else 0
    flags = []
    for bit, (mask, severity, description) in THROTTLE_BITS.items():
        if value & (1 << bit):
            flags.append({"bit": bit, "mask": mask, "severity": severity, "description": description})
    return value, "0x%x" % value, flags


def read_usb_pd_max_ma():
    """USB-PD negotiated current from device tree (big-endian u32, mA)."""
    path = "/proc/device-tree/chosen/power/max_current"
    try:
        with open(path, "rb") as f:
            raw = f.read(4)
    except OSError:
        return None
    return int.from_bytes(raw, "big") if len(raw) == 4 else None


def test_power(soc_id):
    throttled, throttled_hex, flags = parse_throttled()

    volts = {}
    for block in ("core", "sdram_c", "sdram_i", "sdram_p"):
        rc, out, _ = vcgencmd("measure_volts", block)
        if rc == 0 and "=" in out:
            volts[block] = out.split("=", 1)[1]

    rc, pmic_temp_out, _ = vcgencmd("measure_temp", "pmic")
    pmic_temp = pmic_temp_out.split("=", 1)[1] if (rc == 0 and "=" in pmic_temp_out) else None

    pmic_rails = {}
    ext5v_v = None
    ext5v_ok = None
    usb_pd_ma = None

    if soc_id == 4:  # BCM2712 / RP1: ADC is built into the PMIC
        rc, adc_out, _ = vcgencmd("pmic_read_adc")
        if rc == 0:
            for line in adc_out.splitlines():
                m = PMIC_RAIL_RE.match(line)
                if m:
                    rail, value, unit = m.group(1), float(m.group(2)), m.group(3)
                    pmic_rails.setdefault(rail, {})["volt" if unit == "V" else "current"] = value
        if "EXT5V_V" in pmic_rails:
            ext5v_v = pmic_rails["EXT5V_V"].get("volt")
            ext5v_ok = EXT5V_MIN_V <= ext5v_v <= EXT5V_MAX_V if ext5v_v is not None else None
        usb_pd_ma = read_usb_pd_max_ma()

    undervoltage = bool(throttled & ((1 << 0) | (1 << 16)))
    status = "FAIL" if (undervoltage or ext5v_ok is False) else "PASS"

    return {
        "status": status,
        "throttled_hex": throttled_hex,
        "active_flags": flags,
        "undervoltage_seen": undervoltage,
        "pmic_temp": pmic_temp,
        "block_volts": volts,
        "pi5_pmic_rails": pmic_rails,
        "pi5_ext5v_v": ext5v_v,
        "pi5_ext5v_ok": ext5v_ok,
        "pi5_usb_pd_max_ma": usb_pd_ma,
    }


# --------------------------------------------------------------------------
# 3. CPU stress test with telemetry
# --------------------------------------------------------------------------

def read_cpu_temp():
    rc, out, _ = vcgencmd("measure_temp")
    return parse_float(out) if rc == 0 else None


def read_arm_clock_mhz():
    rc, out, _ = vcgencmd("measure_clock", "arm")
    m = re.search(r"=(\d+)", out)
    return round(int(m.group(1)) / 1_000_000) if (rc == 0 and m) else None


def start_cpu_load(seconds):
    """stress-ng -> stress -> built-in load generator using sys.executable."""
    cores = os.cpu_count() or 1
    if shutil.which("stress-ng"):
        return [subprocess.Popen(["stress-ng", "--cpu", str(cores), "--timeout", "%ds" % seconds],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)], "stress-ng"
    if shutil.which("stress"):
        return [subprocess.Popen(["stress", "--cpu", str(cores), "--timeout", "%ds" % seconds],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)], "stress"
    code = "import time; end = time.time() + %d\nwhile time.time() < end:\n    pass" % seconds
    procs = [subprocess.Popen([sys.executable, "-c", code],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
             for _ in range(cores)]
    return procs, "builtin"


def stop_cpu_load(procs):
    for p in procs:
        if p.poll() is None:
            p.terminate()
    for p in procs:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()


def test_cpu_stress(seconds):
    idle_temp = read_cpu_temp()
    idle_mhz = read_arm_clock_mhz()

    procs, engine = start_cpu_load(seconds)
    peak_temp, peak_mhz, samples = idle_temp, idle_mhz, []
    active_throttle = 0
    deadline = time.time() + seconds + 10
    try:
        while any(p.poll() is None for p in procs) and time.time() < deadline:
            time.sleep(2)
            temp = read_cpu_temp()
            mhz = read_arm_clock_mhz()
            active_throttle |= parse_throttled()[0] & THROTTLE_ACTIVE_BITS
            if temp is not None:
                peak_temp = temp if peak_temp is None else max(peak_temp, temp)
            if mhz is not None:
                peak_mhz = mhz if peak_mhz is None else max(peak_mhz, mhz)
            samples.append({"t": round(time.time(), 1), "temp_c": temp, "clock_mhz": mhz})
    finally:
        # Capture throttling at peak load: bits reset after the processes stop
        active_throttle |= parse_throttled()[0] & THROTTLE_ACTIVE_BITS
        stop_cpu_load(procs)

    _, throttled_hex, _ = parse_throttled()

    if (peak_temp is not None and peak_temp >= STRESS_FAIL_TEMP_C) or active_throttle:
        status = "FAIL"
    else:
        status = "PASS"

    return {
        "status": status,
        "engine": engine,
        "duration_s": seconds,
        "idle_temp_c": idle_temp,
        "peak_temp_c": peak_temp,
        "idle_clock_mhz": idle_mhz,
        "peak_clock_mhz": peak_mhz,
        "temp_warning": bool(peak_temp is not None and peak_temp >= STRESS_WARN_TEMP_C),
        "active_throttling_during_test": bool(active_throttle),
        "post_stress_throttled": throttled_hex,
        "telemetry_samples": samples,
    }


# --------------------------------------------------------------------------
# 4. GPIO self-test via pinctrl
# --------------------------------------------------------------------------

def test_gpio():
    if not shutil.which("pinctrl"):
        return {"status": "SKIP", "reason": "pinctrl utility not found (raspi-utils package)"}

    details, failed, skipped = {}, [], []
    for pin in SAFE_TEST_GPIOS:
        rc_set, _, err_set = run(["pinctrl", "set", str(pin), "ip", "pu"])
        if rc_set != 0:
            # The pin is occupied by an overlay or kernel driver; this is not an electrical fault.
            skipped.append(pin)
            details["GPIO%d" % pin] = {"status": "SKIP", "error": err_set or "pinctrl set failed"}
            continue
        time.sleep(0.02)
        _, pu_out, _ = run(["pinctrl", "get", str(pin)])
        pu_match = PIN_LEVEL_RE.search(pu_out)
        pu_ok = bool(pu_match and pu_match.group(1) == "hi")

        run(["pinctrl", "set", str(pin), "ip", "pd"])
        time.sleep(0.02)
        _, pd_out, _ = run(["pinctrl", "get", str(pin)])
        pd_match = PIN_LEVEL_RE.search(pd_out)
        pd_ok = bool(pd_match and pd_match.group(1) == "lo")

        run(["pinctrl", "set", str(pin), "ip", "pn"])

        ok = pu_ok and pd_ok
        if not ok:
            failed.append(pin)
        details["GPIO%d" % pin] = {
            "pull_up_reads_hi": pu_ok,
            "pull_down_reads_lo": pd_ok,
            "raw": {"pu": pu_out, "pd": pd_out},
            "status": "PASS" if ok else "FAIL",
        }

    return {
        "status": "PASS" if not failed else "FAIL",
        "tested_pins_count": len(SAFE_TEST_GPIOS) - len(skipped),
        "failed_pins": failed,
        "skipped_pins": skipped,
        "details": details,
    }


# --------------------------------------------------------------------------
# 5. Peripherals and system integration
# --------------------------------------------------------------------------

def test_peripherals():
    _, net_out, _ = run(["ip", "-br", "link"])
    _, usb_out, _ = run(["lsusb"])
    _, i2c_out, _ = run(["i2cdetect", "-l"])
    bt_rc, bt_out, _ = run(["bluetoothctl", "show"], timeout=10)
    rc_cam, cam_out, cam_err = run(["rpicam-hello", "--list-cameras"], timeout=20)

    return {
        "status": "INFO",
        "network_interfaces": [line for line in net_out.splitlines() if line.strip()],
        "usb_devices": [line for line in usb_out.splitlines() if line.strip()],
        "i2c_buses": [line for line in i2c_out.splitlines() if line.strip()],
        "bluetooth": {"available": bt_rc == 0 and "Powered: yes" in bt_out,
                      "status": "PASS" if bt_rc == 0 else "SKIP"},
        "csi_cameras_available": rc_cam == 0,
        "csi_cameras": [line for line in cam_out.splitlines() if line.strip()],
        "csi_cameras_error": cam_err if rc_cam != 0 else None,
    }


def test_system():
    mounts = read_text("/proc/mounts")
    overlay_active = bool(re.search(r"^overlay\s+/\s+overlay\b", mounts, re.M))

    boot_opts = None
    for line in mounts.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] == BOOT_MOUNT:
            boot_opts = parts[3]
            break

    boot_ro = bool(boot_opts and "ro" in boot_opts.split(","))
    # Status used to always be INFO, preventing the System section from receiving
    # any points even on a healthy board.
    status = "PASS" if (overlay_active and boot_ro) else "WARN"

    return {
        "status": status,
        "kernel": os.uname().release,
        "hostname": socket.gethostname(),
        "overlayroot_active": overlay_active,
        "cmdline": read_text("/proc/cmdline").strip(),
        "boot_mount_options": boot_opts,
        "boot_ro": boot_ro,
    }


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------

def _safe_name(value):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(value))


def _html_value(value):
    return html.escape("—" if value is None else str(value))


def calculate_scores(identity, power, stress, gpio, peripherals, system):
    """Aggregate health score, not a synthetic benchmark.

    Maximum values represent PiDiagOS diagnostic coverage weights:
    board/RAM integrity 1000, power 1500, CPU 2000, GPIO 1000,
    network 1000, USB 500, Bluetooth 500, camera 500, and system 1000.
    """
    scores = []
    def add(name, maximum, value, status):
        scores.append({"component": name, "score": int(value), "max": maximum,
                       "status": status})

    add("Board and RAM", 1000, 1000 if identity.get("status") == "PASS" else 0,
        identity.get("status", "ERROR"))
    add("Power", 1500, 1500 if power.get("status") == "PASS" else 0,
        power.get("status", "ERROR"))

    if stress.get("status") == "PASS":
        cpu_score = 2000
    elif stress.get("status") == "SKIP":
        cpu_score = 0
    else:
        cpu_score = 0
    add("CPU", 2000, cpu_score, stress.get("status", "ERROR"))
    add("GPIO", 1000, 1000 if gpio.get("status") == "PASS" else 0,
        gpio.get("status", "ERROR"))

    net = peripherals.get("network_interfaces", [])
    usb = peripherals.get("usb_devices", [])
    bt = peripherals.get("bluetooth", {})
    add("Network", 1000, 1000 if net else 0, "PASS" if net else "FAIL")
    add("USB", 500, 500 if usb else 0, "PASS" if usb else "INFO")
    add("Bluetooth", 500, 500 if bt.get("available") else 0,
        "PASS" if bt.get("available") else "SKIP")
    add("Video/Camera", 500, 500 if peripherals.get("csi_cameras_available") else 0,
        "PASS" if peripherals.get("csi_cameras_available") else "SKIP")
    add("System", 1000, 1000 if system.get("status") == "PASS" else 0,
        system.get("status", "INFO"))
    return {"score": sum(x["score"] for x in scores),
            "max": sum(x["max"] for x in scores), "components": scores}


def _table(rows):
    body = "".join(
        "<tr><th>%s</th><td>%s</td></tr>" % (_html_value(key), _html_value(value))
        for key, value in rows
    )
    return "<table>%s</table>" % body


def build_html(report):
    verdict = report["overall_status"]
    color = "#1e8e3e" if verdict == "PASS" else "#d93025"
    identity = report.get("identity", {})
    decoded = identity.get("decoded", {})
    power = report.get("power", {})
    stress = report.get("stress", {})
    gpio = report.get("gpio", {})
    system = report.get("system", {})
    scores = report.get("scores", {})

    failed_pins = gpio.get("failed_pins", [])

    sections = [
        ("Board", _table([
            ("Model (device tree)", identity.get("model_dt")),
            ("Serial number", identity.get("serial")),
            ("Revision code", identity.get("revision_hex")),
            ("Board type", decoded.get("board_type")),
            ("SoC", decoded.get("soc")),
            ("Memory (factory / detected, MB)", "%s / %s" % (_html_value(decoded.get("factory_ram_mb")),
                                                      _html_value(decoded.get("detected_ram_mb")))),
            ("Status", identity.get("status", identity.get("error"))),
        ])),
        ("Power", _table([
            ("Status", power.get("status", power.get("error"))),
            ("get_throttled", power.get("throttled_hex")),
            ("Active flags", len(power.get("active_flags", []))),
            ("PMIC temperature", power.get("pmic_temp")),
            ("EXT5V, V", power.get("pi5_ext5v_v")),
            ("USB-PD max, mA", power.get("pi5_usb_pd_max_ma")),
        ])),
        ("CPU stress test (%s s)" % _html_value(stress.get("duration_s")), _table([
            ("Status", stress.get("status", stress.get("error"))),
            ("Temperature: idle / peak, °C", "%s / %s" % (_html_value(stress.get("idle_temp_c")),
                                                         _html_value(stress.get("peak_temp_c")))),
            ("Clock: idle / peak, MHz", "%s / %s" % (_html_value(stress.get("idle_clock_mhz")),
                                                       _html_value(stress.get("peak_clock_mhz")))),
            ("get_throttled after test", stress.get("post_stress_throttled")),
            ("Load engine", stress.get("engine")),
        ])),
        ("GPIO", _table([
            ("Status", gpio.get("status", gpio.get("error"))),
            ("Pins tested", gpio.get("tested_pins_count")),
            ("Failed pins", ", ".join("GPIO%d" % p for p in failed_pins) or "none"),
        ])),
        ("System", _table([
            ("Kernel", system.get("kernel")),
            ("overlayroot active", system.get("overlayroot_active")),
            ("/boot/firmware read-only", system.get("boot_ro")),
        ])),
    ]

    body = "<h3>Score breakdown</h3>" + _table(
        [(item["component"], "%s / %s (%s)" % (item["score"], item["max"], item["status"]))
         for item in scores.get("components", [])]
        + [("Total", "%s / %s" % (scores.get("score", 0), scores.get("max", 0)))]
    ) + "\n" + "\n".join("<h3>%s</h3>%s" % (_html_value(title), content) for title, content in sections)

    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>PiDiagOS Report: %(verdict)s %(board)s (%(serial)s)</title>
<style>
body { font-family: system-ui, sans-serif; max-width: 880px; margin: 24px auto; padding: 0 16px; color: #111; }
.banner { background: %(color)s; color: #fff; padding: 16px 24px; border-radius: 8px; font-size: 22px; font-weight: 700; }
table { width: 100%%; border-collapse: collapse; margin-top: 8px; }
th, td { border: 1px solid #ddd; padding: 8px 10px; text-align: left; font-size: 14px; vertical-align: top; }
th { background: #f5f5f5; width: 38%%; }
pre { background: #f8f9fa; padding: 12px; border-radius: 6px; overflow-x: auto; font-size: 12px; }
</style></head><body>
<div class="banner">TEST RESULT: %(verdict)s — %(model)s</div>
%(body)s
<h3>Full report (JSON)</h3>
<pre>%(json)s</pre>
</body></html>
""" % {
        "verdict": _html_value(verdict),
        "color": color,
        "board": _html_value(decoded.get("board_type")),
        "serial": _html_value(identity.get("serial")),
        "model": _html_value(identity.get("model_dt")),
        "body": body,
        "json": _html_value(json.dumps(report, ensure_ascii=False, indent=2)),
    }


def iter_export_targets():
    """Removable partitions with supported filesystems: (device, filesystem).

    Partitions already mounted by the system (including the boot device) are
    skipped: writing to a live system partition is unsafe.
    """
    rc, out, _ = run(["lsblk", "-P", "-o", "NAME,RM,TYPE,FSTYPE"], timeout=15)
    if rc != 0:
        return []
    in_use = {line.split()[0] for line in read_text("/proc/mounts").splitlines() if line.split()}
    targets = []
    for line in out.splitlines():
        fields = dict(re.findall(r'(\w+)="([^"]*)"', line))
        if fields.get("TYPE") != "part" or fields.get("RM") != "1":
            continue
        if fields.get("FSTYPE") not in ("vfat", "ext4", "exfat", "ntfs"):
            continue
        device = "/dev/" + fields.get("NAME", "")
        if device in in_use:
            continue
        targets.append(fields.get("NAME"))
    return targets


def export_to_usb(paths):
    exported = []
    for dev in iter_export_targets():
        try:
            os.makedirs(USB_MOUNT, exist_ok=True)
        except OSError:
            return exported
        rc, _, err = run(["mount", "/dev/" + dev, USB_MOUNT], timeout=30)
        if rc != 0:
            continue
        try:
            target = os.path.join(USB_MOUNT, "PiDiagOS_Results")
            os.makedirs(target, exist_ok=True)
            for path in paths:
                shutil.copy2(path, target)
            exported.append("/dev/" + dev)
        except OSError:
            pass
        finally:
            run(["sync"])
            run(["umount", USB_MOUNT], timeout=30)
    return exported


def export_reports(report):
    stamp = now_stamp()
    identity = report.get("identity", {})
    board = _safe_name(identity.get("decoded", {}).get("board_type", "Unknown"))
    serial = _safe_name(str(identity.get("serial", "0000000000000000"))[-8:])
    base_name = "%s_%s_%s_%s" % (report["overall_status"], board, serial, stamp.strftime("%Y%m%d_%H%M%S"))

    json_path = os.path.join(RESULTS_DIR_BOOT, base_name + ".json")
    html_path = os.path.join(RESULTS_DIR_BOOT, base_name + ".html")
    latest_path = os.path.join(RESULTS_DIR_BOOT, "index.html")

    run(["mount", "-o", "remount,rw", BOOT_MOUNT])
    try:
        os.makedirs(RESULTS_DIR_BOOT, exist_ok=True)

        html_content = build_html(report)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        for path in (html_path, latest_path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(html_content)

        report["export"] = {
            "json": json_path,
            "html": html_path,
            "usb_devices": export_to_usb([json_path, html_path]),
        }
        # Export information is appended to the already-saved report
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    finally:
        run(["sync"])
        run(["mount", "-o", "remount,ro", BOOT_MOUNT])
    return json_path, html_path


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def acquire_lock():
    try:
        import fcntl
    except ImportError:
        return None
    try:
        fh = open(LOCK_PATH, "w")
    except OSError:
        return None
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def run_safely(name, func, *args):
    try:
        return func(*args)
    except Exception as exc:  # a failed check must not abort the entire report
        return {"status": "ERROR", "error": "%s: %s" % (type(exc).__name__, exc)}


def start_full_test():
    """Full run with stress test in a separate process (web button)."""
    cmd = [sys.executable, os.path.abspath(__file__),
           "--stress-seconds", str(DEFAULT_STRESS_SECONDS)]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def main():
    parser = argparse.ArgumentParser(description="PiDiagOS hardware verification suite")
    parser.add_argument("--serve", action="store_true", help="start the web server for reports")
    parser.add_argument("--port", type=int, default=WEB_PORT)
    parser.add_argument("--stress-seconds", type=int, default=DEFAULT_STRESS_SECONDS)
    parser.add_argument("--skip-stress", action="store_true")
    args = parser.parse_args()

    lock = acquire_lock()
    if lock is None and os.path.exists(LOCK_PATH):
        print("[PiDiagOS] Diagnostics already running; exiting.")
        return 0

    set_led_state("TESTING")

    identity = run_safely("identity", test_identity_and_ram)
    soc_id = identity.get("decoded", {}).get("soc_id") if identity.get("status") != "ERROR" else None

    power = run_safely("power", test_power, soc_id or 0)
    if args.skip_stress:
        stress = {"status": "SKIP", "duration_s": 0}
    else:
        stress = run_safely("stress", test_cpu_stress, args.stress_seconds)
    gpio = run_safely("gpio", test_gpio)
    peripherals = run_safely("peripherals", test_peripherals)
    system = run_safely("system", test_system)

    checked = [identity.get("status"), power.get("status"), stress.get("status"), gpio.get("status")]
    overall = "FAIL" if any(s in ("FAIL", "ERROR") for s in checked) else "PASS"

    report = {
        "tool": "PiDiagOS",
        "timestamp": now_stamp().isoformat(timespec="seconds"),
        "overall_status": overall,
        "identity": identity,
        "power": power,
        "stress": stress,
        "gpio": gpio,
        "peripherals": peripherals,
        "system": system,
    }
    report["scores"] = calculate_scores(identity, power, stress, gpio, peripherals, system)

    print("[PiDiagOS] Diagnostics complete: %s" % overall)
    try:
        json_path, html_path = export_reports(report)
        print("[PiDiagOS] Reports: %s | %s" % (json_path, html_path))
        for dev in report.get("export", {}).get("usb_devices", []):
            print("[PiDiagOS] Report copy on %s" % dev)
    except Exception as exc:  # a report write failure must not interrupt LED status or the web server
        print("[PiDiagOS] Failed to write reports: %s: %s" % (type(exc).__name__, exc),
              file=sys.stderr)

    set_led_state(overall)

    if args.serve:
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

        # Do not hold the lock for the lifetime of the server: the full test started
        # from the web button runs in a separate process and needs the same lock.
        if lock is not None:
            try:
                lock.close()
            except OSError:
                pass
            lock = None

        try:
            os.makedirs(RESULTS_DIR_BOOT, exist_ok=True)
        except OSError:
            pass

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=RESULTS_DIR_BOOT, **kw)

            def do_GET(self):
                if self.path.split("?")[0].rstrip("/") == "/start-full":
                    start_full_test()
                    self.send_response(303)
                    self.send_header("Location", "/")
                    self.end_headers()
                    return
                super().do_GET()

            def log_message(self, fmt, *a):
                sys.stderr.write("[PiDiagOS] %s\n" % (fmt % a))

        print("[PiDiagOS] Web reports: http://%s:%d/" % (socket.gethostname(), args.port))
        ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()

    return 0


if __name__ == "__main__":
    sys.exit(main())
