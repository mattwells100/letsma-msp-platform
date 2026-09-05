#!/usr/bin/env python3
"""
apply_invoice_preview.py  -  Letsma MSP Platform
------------------------------------------------------------------
Adds an Invoice Preview & Approve screen (Option A: preview existing
DRAFT invoices before pushing to Xero).

Run from the repo root (folder containing `app/`):

    cd ~/Downloads/letsma-msp-platform/msp-app
    python apply_invoice_preview.py

What it changes:
  * NEW template app/templates/billing_preview.html  (byte-perfect)
  * app/routers/portal.py       -> adds GET /billing-preview page route
  * app/routers/billing.py      -> adds DELETE /invoices/{id}
                                   (guarded: refuses if pushed to Xero)
  * app/templates/base.html     -> adds a "Invoice Preview" nav link
                                   (only if the anchor is found)

Safety: idempotent (safe to re-run), backs up any file before editing,
validates Python parses, aborts writing a .py file if an anchor is
missing. NO database migration required.
"""
import base64, os, sys, shutil, datetime

APP = "app"
if not os.path.isdir(APP):
    print("ERROR: no 'app/' directory here. cd into the repo root (msp-app) first.")
    sys.exit(1)

def read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def write(p, c):
    with open(p, "w", encoding="utf-8") as f:
        f.write(c)

def backup(p):
    if os.path.exists(p):
        b = p + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(p, b)
        print("  [backup]   %s -> %s" % (p, b))

BILLING_PREVIEW_HTML = "eyUgZXh0ZW5kcyAiYmFzZS5odG1sIiAlfQp7JSBibG9jayB0aXRsZSAlfUludm9pY2UgUHJldmlldyAtIExldHNtYSBNU1B7JSBlbmRibG9jayAlfQp7JSBibG9jayBjb250ZW50ICV9Cgo8ZGl2IGNsYXNzPSJkLWZsZXgganVzdGlmeS1jb250ZW50LWJldHdlZW4gYWxpZ24taXRlbXMtY2VudGVyIG1iLTEiPgogICAgPGgyIGNsYXNzPSJwYWdlLXRpdGxlIG1iLTAiPkludm9pY2UgUHJldmlldyAmYW1wOyBBcHByb3ZlPC9oMj4KICAgIDxkaXY+CiAgICAgICAgPGEgY2xhc3M9ImJ0biBidG4tb3V0bGluZS1zZWNvbmRhcnkiIGhyZWY9Ii9iaWxsaW5nIj48aSBjbGFzcz0iYmkgYmktYXJyb3ctbGVmdCI+PC9pPiBCYWNrIHRvIEJpbGxpbmc8L2E+CiAgICAgICAgeyUgaWYgZHJhZnRzICV9CiAgICAgICAgPGJ1dHRvbiBjbGFzcz0iYnRuIGJ0bi1zdWNjZXNzIiBvbmNsaWNrPSJwdXNoQWxsKCkiPjxpIGNsYXNzPSJiaSBiaS1jbG91ZC11cGxvYWQiPjwvaT4gUHVzaCBBbGwgdG8gWGVybzwvYnV0dG9uPgogICAgICAgIHslIGVuZGlmICV9CiAgICA8L2Rpdj4KPC9kaXY+CjxkaXYgY2xhc3M9InRleHQtbXV0ZWQgbWItNCI+UmV2aWV3IGV2ZXJ5IGRyYWZ0IGludm9pY2UgYW5kIGl0cyBsaW5lIGl0ZW1zIDxzdHJvbmc+YmVmb3JlPC9zdHJvbmc+IGFueXRoaW5nIGlzIHNlbnQgdG8gWGVyby4gR2VuZXJhdGUgZHJhZnRzIGZyb20gQmlsbGluZyBTZXR0aW5ncywgY2hlY2sgdGhlbSBoZXJlLCB0aGVuIGFwcHJvdmUuPC9kaXY+Cgo8ZGl2IGlkPSJyZXN1bHRNc2ciIGNsYXNzPSJtYi0zIj48L2Rpdj4KCnslIGlmIG5vdCBkcmFmdHMgJX0KPGRpdiBjbGFzcz0iY2FyZCBzdGF0LWNhcmQgcC00IHRleHQtY2VudGVyIHRleHQtbXV0ZWQiPgogICAgPGRpdj48aSBjbGFzcz0iYmkgYmktaW5ib3giIHN0eWxlPSJmb250LXNpemU6MnJlbTsiPjwvaT48L2Rpdj4KICAgIE5vIGRyYWZ0IGludm9pY2VzIGF3YWl0aW5nIGFwcHJvdmFsLiBHZW5lcmF0ZSBhIG1vbnRobHkgaW52b2ljZSBydW4gZmlyc3QsIHRoZW4gcmV2aWV3IGl0IGhlcmUuCjwvZGl2Pgp7JSBlbHNlICV9Cgo8ZGl2IGNsYXNzPSJjYXJkIHN0YXQtY2FyZCBwLTMgbWItNCI+CiAgICA8ZGl2IGNsYXNzPSJyb3cgdGV4dC1jZW50ZXIiPgogICAgICAgIDxkaXYgY2xhc3M9ImNvbCI+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9InRleHQtbXV0ZWQgc21hbGwiPkRyYWZ0IEludm9pY2VzPC9kaXY+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9Img0IG1iLTAiPnt7IGRyYWZ0c3xsZW5ndGggfX08L2Rpdj4KICAgICAgICA8L2Rpdj4KICAgICAgICA8ZGl2IGNsYXNzPSJjb2wiPgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJ0ZXh0LW11dGVkIHNtYWxsIj5TdWJ0b3RhbCAoZXggVkFUKTwvZGl2PgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJoNCBtYi0wIj4mcG91bmQ7e3sgJyUuMmYnfGZvcm1hdChncmFuZF9zdWJ0b3RhbCkgfX08L2Rpdj4KICAgICAgICA8L2Rpdj4KICAgICAgICA8ZGl2IGNsYXNzPSJjb2wiPgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJ0ZXh0LW11dGVkIHNtYWxsIj5WQVQ8L2Rpdj4KICAgICAgICAgICAgPGRpdiBjbGFzcz0iaDQgbWItMCI+JnBvdW5kO3t7ICclLjJmJ3xmb3JtYXQoZ3JhbmRfdGF4KSB9fTwvZGl2PgogICAgICAgIDwvZGl2PgogICAgICAgIDxkaXYgY2xhc3M9ImNvbCI+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9InRleHQtbXV0ZWQgc21hbGwiPlRvdGFsIChpbmMgVkFUKTwvZGl2PgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJoNCBtYi0wIj4mcG91bmQ7e3sgJyUuMmYnfGZvcm1hdChncmFuZF90b3RhbCkgfX08L2Rpdj4KICAgICAgICA8L2Rpdj4KICAgIDwvZGl2Pgo8L2Rpdj4KCnslIGZvciBpbnYgaW4gZHJhZnRzICV9CjxkaXYgY2xhc3M9ImNhcmQgc3RhdC1jYXJkIHAtMyBtYi0zIiBpZD0iY2FyZC17eyBpbnYuaWQgfX0iPgogICAgPGRpdiBjbGFzcz0iZC1mbGV4IGp1c3RpZnktY29udGVudC1iZXR3ZWVuIGFsaWduLWl0ZW1zLWNlbnRlciI+CiAgICAgICAgPGRpdj4KICAgICAgICAgICAgPGg1IGNsYXNzPSJtYi0wIj57eyBpbnYuY3VzdG9tZXIubmFtZSBpZiBpbnYuY3VzdG9tZXIgZWxzZSAnVW5rbm93biBjdXN0b21lcicgfX08L2g1PgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJ0ZXh0LW11dGVkIHNtYWxsIj4KICAgICAgICAgICAgICAgIHt7IGludi5pbnZvaWNlX251bWJlciBvciBpbnYuaWRbOjhdIH19CiAgICAgICAgICAgICAgICB7JSBpZiBpbnYuYmlsbGluZ19wZXJpb2Rfc3RhcnQgJX0gJm1pZGRvdDsge3sgaW52LmJpbGxpbmdfcGVyaW9kX3N0YXJ0LnN0cmZ0aW1lKCclQiAlWScpIH19eyUgZW5kaWYgJX0KICAgICAgICAgICAgICAgICZtaWRkb3Q7IHt7IGludi5saW5lX2l0ZW1zfGxlbmd0aCB9fSBsaW5le3sgJycgaWYgaW52LmxpbmVfaXRlbXN8bGVuZ3RoID09IDEgZWxzZSAncycgfX0KICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgPC9kaXY+CiAgICAgICAgPGRpdiBjbGFzcz0idGV4dC1lbmQiPgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJoNSBtYi0wIj4mcG91bmQ7e3sgJyUuMmYnfGZvcm1hdChpbnYudG90YWwpIH19PC9kaXY+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9InRleHQtbXV0ZWQgc21hbGwiPmluYyBWQVQ8L2Rpdj4KICAgICAgICA8L2Rpdj4KICAgIDwvZGl2PgoKICAgIHslIHNldCBoYXNfemVybyA9IGludi5saW5lX2l0ZW1zfHNlbGVjdGF0dHIoJ3VuaXRfcHJpY2UnLCAnZXF1YWx0bycsIDApfGxpc3QgJX0KICAgIHslIGlmIG5vdCBpbnYubGluZV9pdGVtcyAlfQogICAgICAgIDxkaXYgY2xhc3M9ImFsZXJ0IGFsZXJ0LXdhcm5pbmcgcHktMiBtdC0yIG1iLTAiPjxpIGNsYXNzPSJiaSBiaS1leGNsYW1hdGlvbi10cmlhbmdsZSI+PC9pPiBUaGlzIGludm9pY2UgaGFzIG5vIGxpbmUgaXRlbXMuPC9kaXY+CiAgICB7JSBlbGlmIGhhc196ZXJvICV9CiAgICAgICAgPGRpdiBjbGFzcz0iYWxlcnQgYWxlcnQtd2FybmluZyBweS0yIG10LTIgbWItMCI+PGkgY2xhc3M9ImJpIGJpLWV4Y2xhbWF0aW9uLXRyaWFuZ2xlIj48L2k+IE9uZSBvciBtb3JlIGxpbmVzIGhhdmUgYSAmcG91bmQ7MC4wMCB1bml0IHByaWNlIC0gcGxlYXNlIHJldmlldyBiZWZvcmUgYXBwcm92aW5nLjwvZGl2PgogICAgeyUgZW5kaWYgJX0KCiAgICA8dGFibGUgY2xhc3M9InRhYmxlIHRhYmxlLXNtIG10LTMgbWItMiI+CiAgICAgICAgPHRoZWFkPgogICAgICAgICAgICA8dHI+CiAgICAgICAgICAgICAgICA8dGg+RGVzY3JpcHRpb248L3RoPgogICAgICAgICAgICAgICAgPHRoIGNsYXNzPSJ0ZXh0LWVuZCI+UXR5PC90aD4KICAgICAgICAgICAgICAgIDx0aCBjbGFzcz0idGV4dC1lbmQiPlVuaXQgKGV4IFZBVCk8L3RoPgogICAgICAgICAgICAgICAgPHRoIGNsYXNzPSJ0ZXh0LWVuZCI+TGluZSBUb3RhbDwvdGg+CiAgICAgICAgICAgIDwvdHI+CiAgICAgICAgPC90aGVhZD4KICAgICAgICA8dGJvZHk+CiAgICAgICAgeyUgZm9yIGxpIGluIGludi5saW5lX2l0ZW1zICV9CiAgICAgICAgICAgIDx0ciB7JSBpZiBsaS51bml0X3ByaWNlID09IDAgJX1jbGFzcz0idGFibGUtd2FybmluZyJ7JSBlbmRpZiAlfT4KICAgICAgICAgICAgICAgIDx0ZD57eyBsaS5kZXNjcmlwdGlvbiB9fTwvdGQ+CiAgICAgICAgICAgICAgICA8dGQgY2xhc3M9InRleHQtZW5kIj57eyBsaS5xdWFudGl0eSB9fTwvdGQ+CiAgICAgICAgICAgICAgICA8dGQgY2xhc3M9InRleHQtZW5kIj4mcG91bmQ7e3sgJyUuMmYnfGZvcm1hdChsaS51bml0X3ByaWNlKSB9fTwvdGQ+CiAgICAgICAgICAgICAgICA8dGQgY2xhc3M9InRleHQtZW5kIj4mcG91bmQ7e3sgJyUuMmYnfGZvcm1hdChsaS5xdWFudGl0eSAqIGxpLnVuaXRfcHJpY2UpIH19PC90ZD4KICAgICAgICAgICAgPC90cj4KICAgICAgICB7JSBlbmRmb3IgJX0KICAgICAgICA8L3Rib2R5PgogICAgICAgIDx0Zm9vdD4KICAgICAgICAgICAgPHRyPjx0ZCBjb2xzcGFuPSIzIiBjbGFzcz0idGV4dC1lbmQgdGV4dC1tdXRlZCI+U3VidG90YWw8L3RkPjx0ZCBjbGFzcz0idGV4dC1lbmQiPiZwb3VuZDt7eyAnJS4yZid8Zm9ybWF0KGludi5zdWJ0b3RhbCkgfX08L3RkPjwvdHI+CiAgICAgICAgICAgIDx0cj48dGQgY29sc3Bhbj0iMyIgY2xhc3M9InRleHQtZW5kIHRleHQtbXV0ZWQiPlZBVCAoMjAlKTwvdGQ+PHRkIGNsYXNzPSJ0ZXh0LWVuZCI+JnBvdW5kO3t7ICclLjJmJ3xmb3JtYXQoaW52LnRheF90b3RhbCkgfX08L3RkPjwvdHI+CiAgICAgICAgICAgIDx0cj48dGQgY29sc3Bhbj0iMyIgY2xhc3M9InRleHQtZW5kIGZ3LWJvbGQiPlRvdGFsPC90ZD48dGQgY2xhc3M9InRleHQtZW5kIGZ3LWJvbGQiPiZwb3VuZDt7eyAnJS4yZid8Zm9ybWF0KGludi50b3RhbCkgfX08L3RkPjwvdHI+CiAgICAgICAgPC90Zm9vdD4KICAgIDwvdGFibGU+CgogICAgPGRpdiBjbGFzcz0iZC1mbGV4IGp1c3RpZnktY29udGVudC1lbmQgZ2FwLTIiPgogICAgICAgIDxidXR0b24gY2xhc3M9ImJ0biBidG4tc20gYnRuLW91dGxpbmUtZGFuZ2VyIiBvbmNsaWNrPSJkZWxldGVEcmFmdCgne3sgaW52LmlkIH19JykiPjxpIGNsYXNzPSJiaSBiaS10cmFzaCI+PC9pPiBEaXNjYXJkPC9idXR0b24+CiAgICAgICAgPGJ1dHRvbiBjbGFzcz0iYnRuIGJ0bi1zbSBidG4tcHJpbWFyeSIgb25jbGljaz0icHVzaE9uZSgne3sgaW52LmlkIH19JykiPjxpIGNsYXNzPSJiaSBiaS1jbG91ZC11cGxvYWQiPjwvaT4gQXBwcm92ZSAmYW1wOyBQdXNoIHRvIFhlcm88L2J1dHRvbj4KICAgIDwvZGl2Pgo8L2Rpdj4KeyUgZW5kZm9yICV9Cgp7JSBlbmRpZiAlfQoKPHNjcmlwdD4KZnVuY3Rpb24gbXNnKGh0bWwsIGtpbmQpIHsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdyZXN1bHRNc2cnKS5pbm5lckhUTUwgPQogICAgICAgICc8ZGl2IGNsYXNzPSJhbGVydCBhbGVydC0nICsgKGtpbmQgfHwgJ2luZm8nKSArICcgcHktMiBtYi0wIj4nICsgaHRtbCArICc8L2Rpdj4nOwp9Cgphc3luYyBmdW5jdGlvbiBwdXNoT25lKGlkKSB7CiAgICB0cnkgewogICAgICAgIGNvbnN0IHJlc3AgPSBhd2FpdCBmZXRjaCgnL2FwaS9iaWxsaW5nL2ludm9pY2VzLycgKyBpZCArICcvcHVzaC10by14ZXJvJywge21ldGhvZDogJ1BPU1QnfSk7CiAgICAgICAgaWYgKHJlc3Aub2spIHsKICAgICAgICAgICAgY29uc3QgY2FyZCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdjYXJkLScgKyBpZCk7CiAgICAgICAgICAgIGlmIChjYXJkKSBjYXJkLnJlbW92ZSgpOwogICAgICAgICAgICBtc2coJ1B1c2hlZCBpbnZvaWNlICcgKyBpZC5zdWJzdHJpbmcoMCw4KSArICcgdG8gWGVyby4nLCAnc3VjY2VzcycpOwogICAgICAgIH0gZWxzZSB7CiAgICAgICAgICAgIGNvbnN0IGRhdGEgPSBhd2FpdCByZXNwLmpzb24oKTsKICAgICAgICAgICAgbXNnKCdQdXNoIGZhaWxlZCBmb3IgJyArIGlkLnN1YnN0cmluZygwLDgpICsgJzogJyArIChkYXRhLmRldGFpbCB8fCBKU09OLnN0cmluZ2lmeShkYXRhKSksICdkYW5nZXInKTsKICAgICAgICB9CiAgICB9IGNhdGNoIChlcnIpIHsKICAgICAgICBtc2coJ1B1c2ggZmFpbGVkOiAnICsgZXJyLCAnZGFuZ2VyJyk7CiAgICB9Cn0KCmFzeW5jIGZ1bmN0aW9uIGRlbGV0ZURyYWZ0KGlkKSB7CiAgICBpZiAoIWNvbmZpcm0oJ0Rpc2NhcmQgdGhpcyBkcmFmdCBpbnZvaWNlPyBJdCB3aWxsIGJlIHBlcm1hbmVudGx5IHJlbW92ZWQgKGl0IGhhcyBub3QgYmVlbiBzZW50IHRvIFhlcm8pLicpKSByZXR1cm47CiAgICB0cnkgewogICAgICAgIGNvbnN0IHJlc3AgPSBhd2FpdCBmZXRjaCgnL2FwaS9iaWxsaW5nL2ludm9pY2VzLycgKyBpZCwge21ldGhvZDogJ0RFTEVURSd9KTsKICAgICAgICBpZiAocmVzcC5vaykgewogICAgICAgICAgICBjb25zdCBjYXJkID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2NhcmQtJyArIGlkKTsKICAgICAgICAgICAgaWYgKGNhcmQpIGNhcmQucmVtb3ZlKCk7CiAgICAgICAgICAgIG1zZygnRHJhZnQgJyArIGlkLnN1YnN0cmluZygwLDgpICsgJyBkaXNjYXJkZWQuJywgJ3NlY29uZGFyeScpOwogICAgICAgIH0gZWxzZSB7CiAgICAgICAgICAgIGNvbnN0IGRhdGEgPSBhd2FpdCByZXNwLmpzb24oKTsKICAgICAgICAgICAgbXNnKCdEaXNjYXJkIGZhaWxlZDogJyArIChkYXRhLmRldGFpbCB8fCBKU09OLnN0cmluZ2lmeShkYXRhKSksICdkYW5nZXInKTsKICAgICAgICB9CiAgICB9IGNhdGNoIChlcnIpIHsKICAgICAgICBtc2coJ0Rpc2NhcmQgZmFpbGVkOiAnICsgZXJyLCAnZGFuZ2VyJyk7CiAgICB9Cn0KCmFzeW5jIGZ1bmN0aW9uIHB1c2hBbGwoKSB7CiAgICBpZiAoIWNvbmZpcm0oJ0FwcHJvdmUgYW5kIHB1c2ggQUxMIGRyYWZ0IGludm9pY2VzIHRvIFhlcm8/JykpIHJldHVybjsKICAgIGNvbnN0IGNhcmRzID0gZG9jdW1lbnQucXVlcnlTZWxlY3RvckFsbCgnW2lkXj0iY2FyZC0iXScpOwogICAgbGV0IG9rID0gMCwgZmFpbCA9IDA7CiAgICBmb3IgKGNvbnN0IGNhcmQgb2YgY2FyZHMpIHsKICAgICAgICBjb25zdCBpZCA9IGNhcmQuaWQucmVwbGFjZSgnY2FyZC0nLCAnJyk7CiAgICAgICAgdHJ5IHsKICAgICAgICAgICAgY29uc3QgcmVzcCA9IGF3YWl0IGZldGNoKCcvYXBpL2JpbGxpbmcvaW52b2ljZXMvJyArIGlkICsgJy9wdXNoLXRvLXhlcm8nLCB7bWV0aG9kOiAnUE9TVCd9KTsKICAgICAgICAgICAgaWYgKHJlc3Aub2spIHsgY2FyZC5yZW1vdmUoKTsgb2srKzsgfQogICAgICAgICAgICBlbHNlIHsgZmFpbCsrOyB9CiAgICAgICAgfSBjYXRjaCAoZXJyKSB7IGZhaWwrKzsgfQogICAgfQogICAgbXNnKCdQdXNoIGNvbXBsZXRlOiAnICsgb2sgKyAnIHN1Y2NlZWRlZCwgJyArIGZhaWwgKyAnIGZhaWxlZC4nLCBmYWlsID8gJ3dhcm5pbmcnIDogJ3N1Y2Nlc3MnKTsKfQo8L3NjcmlwdD4KeyUgZW5kYmxvY2sgJX0K"

# ------------------------------------------------------------------
# 1. Template
# ------------------------------------------------------------------
print("\n== 1/4  Template ==")
tpl_path = os.path.join(APP, "templates", "billing_preview.html")
os.makedirs(os.path.dirname(tpl_path), exist_ok=True)
data = base64.b64decode(BILLING_PREVIEW_HTML)
with open(tpl_path, "wb") as f:
    f.write(data)
print("  [template] wrote billing_preview.html (%d bytes)" % len(data))

# ------------------------------------------------------------------
# 2. portal.py  - preview page route
# ------------------------------------------------------------------
print("\n== 2/4  app/routers/portal.py ==")
p_path = os.path.join(APP, "routers", "portal.py")
p = read(p_path)
if "billing_preview_page" in p:
    print("  [skip]     preview route already present")
else:
    route = '''

@router.get("/billing-preview")
def billing_preview_page(request: Request, db: Session = Depends(get_db), _=Depends(require_login_page)):
    # Only DRAFT invoices that have NOT been pushed to Xero are shown for
    # review/approval - anything already synced is out of scope here.
    drafts = (
        db.query(models.Invoice)
        .filter(models.Invoice.xero_invoice_id.is_(None))
        .filter(models.Invoice.status == models.InvoiceStatus.DRAFT)
        .order_by(models.Invoice.created_at.desc())
        .all()
    )
    grand_subtotal = sum((inv.subtotal or 0) for inv in drafts)
    grand_tax = sum((inv.tax_total or 0) for inv in drafts)
    grand_total = sum((inv.total or 0) for inv in drafts)
    return templates.TemplateResponse("billing_preview.html", {
        "request": request, "drafts": drafts,
        "grand_subtotal": grand_subtotal, "grand_tax": grand_tax, "grand_total": grand_total,
        "active_page": "billing",
    })
'''
    backup(p_path)
    write(p_path, p.rstrip() + "\n" + route)
    print("  [add]      appended /billing-preview page route")

# ------------------------------------------------------------------
# 3. billing.py  - guarded DELETE draft endpoint
# ------------------------------------------------------------------
print("\n== 3/4  app/routers/billing.py ==")
b_path = os.path.join(APP, "routers", "billing.py")
b = read(b_path)
if "def delete_invoice" in b:
    print("  [skip]     delete-invoice endpoint already present")
else:
    endpoint = '''

@router.delete("/invoices/{invoice_id}")
def delete_invoice(invoice_id: str, db: Session = Depends(get_db)):
    """
    Discard a DRAFT invoice that has NOT been pushed to Xero. Refuses to
    delete anything already synced to Xero (delete/void it in Xero
    instead) so local and Xero records can never silently diverge.
    """
    invoice = db.query(models.Invoice).get(invoice_id)
    if not invoice:
        raise HTTPException(404, "Invoice not found")
    if invoice.xero_invoice_id:
        raise HTTPException(400, "Invoice already pushed to Xero - cannot discard here.")
    db.delete(invoice)
    db.commit()
    return {"status": "ok", "deleted": invoice_id}
'''
    backup(b_path)
    write(b_path, b.rstrip() + "\n" + endpoint)
    print("  [add]      appended DELETE /invoices/{id} endpoint")

# ------------------------------------------------------------------
# 4. base.html  - nav link (best-effort, guarded by anchor)
# ------------------------------------------------------------------
print("\n== 4/4  app/templates/base.html ==")
base_path = os.path.join(APP, "templates", "base.html")
if not os.path.exists(base_path):
    print("  [WARN]     base.html not found - skipping nav link")
else:
    bh = read(base_path)
    if "/billing-preview" in bh:
        print("  [skip]     nav link already present")
    else:
        # Anchor: the Billing nav link. Insert a new <li> right after it.
        import re
        m = re.search(r'(<li>\s*<a href="/billing".*?</a>\s*</li>)', bh, re.S)
        if m:
            block = m.group(1)
            navlink = block + '''
            <li>
                <a href="/billing-preview" class="nav-link {% if active_page=='billing-preview' %}active{% endif %}"><i class="bi bi-search me-2"></i>Invoice Preview</a>
            </li>'''
            backup(base_path)
            write(base_path, bh.replace(block, navlink, 1))
            print("  [add]      inserted Invoice Preview nav link")
        else:
            print("  [WARN]     could not find the Billing nav <li> anchor.")
            print("             Add a link to /billing-preview in base.html manually if you want it in the sidebar.")
            print("             (The page still works directly at /billing-preview.)")

# ------------------------------------------------------------------
# Validate the two edited .py files parse
# ------------------------------------------------------------------
print("\n== Verifying ==")
import ast
ok = True
for f in [p_path, b_path]:
    try:
        ast.parse(read(f))
        print("  %s: valid Python" % f)
    except SyntaxError as e:
        print("  [ERROR] %s: %s" % (f, e))
        ok = False
if not ok:
    sys.exit(1)

print("""
==================================================================
 DONE (no migration needed). Next steps:

   git add -A
   git commit -m "Add invoice preview & approve screen"
   git checkout main && git pull origin main
   git merge add-email-to-ticket
   git push origin main
   git checkout add-email-to-ticket

 Then, after deploy:
   1. Generate a monthly run (creates DRAFT invoices, nothing to Xero).
   2. Open  /billing-preview
   3. Review each customer's lines (incl. recurring items).
   4. "Approve & Push to Xero" per invoice, or "Push All to Xero".
==================================================================
""")
