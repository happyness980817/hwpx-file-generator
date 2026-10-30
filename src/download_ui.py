"""Start a browser download after the current Streamlit run builds a file.

Call only from the download button's success branch, after reading the current
form values and generating their archive. A fresh request ID represents an
explicit click; re-rendering that ID must never download the file twice.
"""
from __future__ import annotations

import base64
import re

from streamlit.components.v2 import component


DOWNLOAD_JS = r"""
export default function({ data, parentElement }) {
    if (!data || !data.requestId || !data.content) return;

    // Page-local IDs only: no customer data or files enter browser storage.
    const stateKey = Symbol.for('kbrand.download.requests');
    const completed = globalThis[stateKey] ??= new Set();
    if (completed.has(data.requestId)) return;

    const link = parentElement.querySelector('a');
    const status = parentElement.querySelector('[role="status"]');
    let objectUrl;
    try {
        const binary = atob(data.content);
        const bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
        objectUrl = URL.createObjectURL(new Blob([bytes], { type: 'application/zip' }));
        // Values are assigned as properties, never interpolated into HTML or JS.
        link.href = objectUrl;
        link.download = data.filename;
        link.click();
        completed.add(data.requestId);
        if (completed.size > 64) completed.delete(completed.values().next().value);
        if (data.showRetry) link.hidden = false;
    } catch (_) {
        status.textContent = '다운로드를 시작하지 못했습니다. 신청서 내려받기를 다시 눌러 주세요.';
        if (objectUrl) URL.revokeObjectURL(objectUrl);
        return;
    }

    return () => {
        // A newly started download may still be consuming the Blob at unmount.
        setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
    };
}
"""

_download = component(
    'kbrand_file_download',
    html='<div role="status" aria-live="polite"></div>'
         '<a hidden>다운로드가 시작되지 않으면 다시 받기</a>',
    css='a, [role="status"] {font: 12px/1.5 sans-serif;color:#86868b;}\n'
        'a {text-underline-offset:3px;}\n[hidden] {display:none!important;}',
    js=DOWNLOAD_JS,
)


def render_file_download(
    content: bytes,
    filename: str,
    *,
    request_id: str,
    show_retry: bool = True,
):
    """Download a generated ZIP without a second mandatory button click.

    The caller owns validation, generation, and the request ID. This function
    neither invokes AI nor writes to a sheet or persistent file store. The
    optional small retry link handles browser policies that block an automatic
    download; it uses the same in-memory bytes and never regenerates the file.
    """
    if not isinstance(content, bytes) or not content:
        raise ValueError('A nonempty ZIP byte string is required.')
    if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', request_id):
        raise ValueError('A unique download request ID is required.')
    if not isinstance(filename, str) or not filename:
        raise ValueError('A download filename is required.')
    safe_filename = re.sub(r'[\\/\x00-\x1f\x7f]', '_', filename)
    return _download(
        key='application_file_download',
        data={
            'content': base64.b64encode(content).decode('ascii'),
            'filename': safe_filename,
            'requestId': request_id,
            'showRetry': show_retry,
        },
        height='content' if show_retry else 0,
    )
