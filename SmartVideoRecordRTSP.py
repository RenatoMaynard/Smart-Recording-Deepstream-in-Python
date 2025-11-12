import os  # filesystem utils
import sys  # exit codes
import ctypes  # C-like structs
import gi  # GObject introspection

gi.require_version("Gst", "1.0")  # ensure GStreamer 1.0
from gi.repository import Gst, GLib  # GStreamer and GLib main loop

import pyds  # DeepStream Python bindings (smart record helpers)

# =========================
# Quick config
# =========================
URI = "rtsp://(...)"  # RTSP source URI
RECORD_DIR = os.path.expanduser("~/Desktop/SmartRecTest")  # output directory
BACK_SEC   = 3        # pre-roll seconds (<= smart-rec-cache)
FRONT_SEC  = 5        # post-roll seconds
CACHE_SEC  = 30       # ring buffer size (seconds)
START_DELAY_SEC = 5   # delay before starting SR

# =========================
# User context struct (matches native)
# =========================
class SRUserContext(ctypes.Structure):  # user context passed to SR
    _fields_ = [  # C-struct fields
        ("sessionid", ctypes.c_int),  # user session id
        ("name", ctypes.c_char * 32),  # user name
    ]

def main():  # entry point
    print("[Main] running…")  # log start
    os.makedirs(RECORD_DIR, exist_ok=True)  # ensure output dir
    Gst.init(None)  # init GStreamer

    pipeline = Gst.Pipeline.new("sr-test")  # create pipeline
    if not pipeline:  # check pipeline
        print("Failed to create pipeline"); return 1  # abort if fail

    nvuri = Gst.ElementFactory.make("nvurisrcbin", "uri-decode-bin")  # DeepStream URI source with decode + SR
    mux   = Gst.ElementFactory.make("nvstreammux", "mux")  # stream muxer
    qsrc  = Gst.ElementFactory.make("queue", "q_src")  # source queue
    conv  = Gst.ElementFactory.make("nvvideoconvert", "conv")  # GPU color/format convert
    sink  = Gst.ElementFactory.make("fakesink", "sink")  # dummy sink

    if not nvuri: print("Failed to create nvurisrcbin"); return 1  # check source
    if not mux or not qsrc or not conv or not sink:  # check others
        print("Missing pipeline elements"); return 1  # abort if fail

    # nvurisrcbin (Smart Record)
    nvuri.set_property("uri", URI)  # set RTSP/file URI
    nvuri.set_property("file-loop", True)  # loop files (ignored for live RTSP)
    nvuri.set_property("smart-record", 2)  # enable SR with full mode
    nvuri.set_property("smart-rec-dir-path", RECORD_DIR)  # SR output dir
    nvuri.set_property("smart-rec-cache", CACHE_SEC)  # preroll cache seconds
    try:
        nvuri.set_property("smart-rec-file-prefix", "test_")  # optional filename prefix
    except Exception:
        pass  # property may not exist

    # nvstreammux
    mux.set_property("batch-size", 1)  # single stream
    mux.set_property("live-source", 0)  # 0=file, 1=live (kept as original)
    mux.set_property("width", 1920)  # muxed width
    mux.set_property("height", 1080)  # muxed height
    mux.set_property("batched-push-timeout", 40000)  # push timeout (µs)

    for e in (nvuri, qsrc, mux, conv, sink):  # add elements
        pipeline.add(e)  # add to pipeline
    if not mux.link(conv) or not conv.link(sink):  # link mux→conv→sink
        print("Link mux→conv→sink FAILED"); return 1  # abort on link fail

    def cb_pad_added(_dbin, src_pad, _u):  # pad-added handler from nvurisrcbin
        sinkpad = mux.request_pad_simple("sink_0")  # request mux sink_0
        if not sinkpad:  # check pad
            print("No sink_0 pad on nvstreammux"); return  # bail if missing
        caps = src_pad.get_current_caps() or src_pad.query_caps()  # get caps
        if caps:  # if we have caps
            st = caps.get_structure(0)  # first structure
            try:
                w = int(st.get_value('width'))  if st.has_field('width')  else 1920  # extract width
                h = int(st.get_value('height')) if st.has_field('height') else 1080  # extract height
                mux.set_property("width", w)  # update mux width
                mux.set_property("height", h)  # update mux height
            except Exception:
                pass  # ignore parse errors
        if src_pad.link(qsrc.get_static_pad("sink")) != Gst.PadLinkReturn.OK:  # link src→queue
            print("Link nvurisrcbin → qsrc FAILED"); return  # report fail
        if qsrc.get_static_pad("src").link(sinkpad) != Gst.PadLinkReturn.OK:  # link queue→mux.sink_0
            print("Link qsrc → mux.sink_0 FAILED")  # report fail

    nvuri.connect("pad-added", cb_pad_added, None)  # connect pad-added

    # ===== SR callbacks and native buffers =====
    SR_DONE = {"got": False}  # flag for SR completion

    def on_sr_done(nvurisrcbin_elem, recordingInfo, user_ctx, user_data):  # SR completion callback
        try:
            info = pyds.NvDsSRRecordingInfo.cast(hash(recordingInfo))  # cast to info
            sr   = pyds.SRUserContext.cast(hash(user_ctx)) if user_ctx else None  # cast user ctx
            print("====== SR DONE ======")  # log
            try:
                print(f"dir:  {pyds.get_string(info.dirpath)}")  # print dir
                print(f"file: {pyds.get_string(info.filename)}")  # print filename
            except Exception:
                print(f"dir:  {getattr(info, 'dirpath', None)}")  # fallback dir
                print(f"file: {getattr(info, 'filename', None)}")  # fallback file
            print(f"size: {info.width}x{info.height}")  # resolution
            if sr:  # if user ctx present
                try:
                    nm = sr.name.decode(errors="ignore")  # decode name
                except Exception:
                    nm = str(getattr(sr, "name", b""))  # fallback name
                print(f"user.sessionid={sr.sessionid}  user.name='{nm}'")  # print user ctx
        except Exception as e:
            print("[SR DONE] error:", e)  # log errors
        finally:
            SR_DONE["got"] = True  # mark done
            GLib.timeout_add_seconds(1, do_quit)  # quit shortly

    nvuri.connect("sr-done", on_sr_done, pipeline)  # connect SR signal

    # gpointers (allocate native buffers)
    sessionid_gbuf = pyds.alloc_buffer(4)  # allocate 4 bytes
    sessionid_ptr  = pyds.get_native_ptr(sessionid_gbuf)  # get native pointer

    ctx_size       = ctypes.sizeof(SRUserContext)  # sizeof struct
    user_ctx_gbuf  = pyds.alloc_buffer(ctx_size)  # allocate struct bytes
    user_ctx_ptr   = pyds.get_native_ptr(user_ctx_gbuf)  # pointer to struct
    srctx = pyds.SRUserContext.cast(user_ctx_ptr)  # map pointer to struct
    srctx.sessionid = 1234  # set session id
    srctx.name      = b"sr-demo"  # set user name

    # ===== Bus / message handling =====
    def on_bus(_bus, msg, _data):  # bus callback
        t = msg.type  # message type
        if t == Gst.MessageType.ERROR:  # error case
            err, dbg = msg.parse_error()  # parse error
            print(f"[GST][ERROR] {err} {dbg}")  # log error
            try:
                pipeline.set_state(Gst.State.NULL)  # stop pipeline
            except Exception:
                pass  # ignore
            if hasattr(do_quit, "_loop"): do_quit._loop.quit()  # end loop
            return True  # handled
        elif t == Gst.MessageType.EOS:  # end-of-stream
            print("[GST] EOS")  # log eos
            if hasattr(do_quit, "_loop"): do_quit._loop.quit()  # end loop
            return True  # handled
        return False  # unhandled

    bus = pipeline.get_bus()  # get bus
    bus.add_signal_watch()  # watch messages
    bus.connect("message", on_bus, None)  # connect handler

    # ===== Scheduled Start / Stop =====
    def do_start():  # start SR
        try:
            back = min(BACK_SEC, int(nvuri.get_property("smart-rec-cache") or BACK_SEC))  # clamp back
            nvuri.emit("start-sr", sessionid_ptr, int(back), int(FRONT_SEC), user_ctx_ptr)  # emit start
            print(f"[SR] start: back={back}s front={FRONT_SEC}s (sessionid OK, user_ctx OK)")  # log
        except Exception as e:
            print("[SR] start error:", e)  # log error
        return False  # one-shot timer

    def do_stop():  # stop SR
        try:
            try:
                nvuri.emit("stop-sr", 0)  # newer signature
            except TypeError:
                nvuri.emit("stop-sr")  # older signature
            print("[SR] stop requested")  # log stop
        except Exception as e:
            print("[SR] stop error:", e)  # log error
        # fallback if sr-done never arrives
        def _fallback():  # timeout fallback
            if not SR_DONE["got"]:  # if no SR_DONE
                print("[SR] sr-done not received; exiting by timeout")  # log
                return do_quit()  # quit
            return False  # no action
        GLib.timeout_add_seconds(6, _fallback)  # schedule fallback
        return False  # one-shot timer

    def do_quit():  # quit app
        print("[Main] bye")  # log
        try:
            pipeline.set_state(Gst.State.NULL)  # stop pipeline
        except Exception:
            pass  # ignore
        if hasattr(do_quit, "_loop"): do_quit._loop.quit()  # stop loop
        return False  # stop timer

    # Start pipeline
    pipeline.set_state(Gst.State.PLAYING)  # set PLAYING

    # Schedule SR start/stop relative to now
    GLib.timeout_add_seconds(START_DELAY_SEC, do_start)  # schedule start
    GLib.timeout_add_seconds(START_DELAY_SEC + FRONT_SEC + 1, do_stop)  # schedule stop

    loop = GLib.MainLoop()  # create main loop
    do_quit._loop = loop  # stash loop on function
    try:
        loop.run()  # run loop
    finally:
        # free native buffers
        try:
            pyds.free_gbuffer(sessionid_gbuf)  # free session buffer
            pyds.free_gbuffer(user_ctx_gbuf)  # free user ctx buffer
        except Exception:
            pass  # ignore
        try:
            pipeline.set_state(Gst.State.NULL)  # ensure stop
        except Exception:
            pass  # ignore

    return 0  # success

if __name__ == "__main__":  # script guard
    sys.exit(main())  # run main and exit with its code
