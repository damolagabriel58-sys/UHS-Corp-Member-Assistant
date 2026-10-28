
import { useCallback, useEffect, useRef, useState } from "react";
import "./App.css";

const API_URL =
  import.meta.env.VITE_API_BASE_URL ||
  "http://127.0.0.1:8000";
function formatDate(value) {
  if (!value) return "—";

  return new Date(value).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDocumentType(value) {
  if (value === "payment_approval") return "Payment Approval";
  if (value === "clearance") return "Clearance";

  return value || "Unknown";
}

function App() {
  const [authStatus, setAuthStatus] = useState("checking");
  const [directorEmail, setDirectorEmail] = useState("");
  const [authError, setAuthError] = useState("");
  const [loggingOut, setLoggingOut] = useState(false);
  const [pdfBlobUrl, setPdfBlobUrl] = useState("");
  const [pdfLoading, setPdfLoading] = useState(false);
  const [pdfError, setPdfError] = useState("");
  const [documents, setDocuments] = useState([]);
  const [signedDocuments, setSignedDocuments] = useState([]);
  const [view, setView] = useState("pending");
  const [selectedYear, setSelectedYear] = useState("all");
  const [historyYear, setHistoryYear] = useState(new Date().getFullYear());
  const [historyYears, setHistoryYears] = useState([]);
  const [clearanceHistory, setClearanceHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [removingId, setRemovingId] = useState(null);
  const [removeMessage, setRemoveMessage] = useState("");
  const [selectedMonth, setSelectedMonth] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [selectedDocument, setSelectedDocument] = useState(null);
  const [approving, setApproving] = useState(false);
  const [approvalError, setApprovalError] = useState("");
  const [signedPreviewUrl, setSignedPreviewUrl] = useState("");
  const [signedPreviewError, setSignedPreviewError] = useState("");
  const [signedDocument, setSignedDocument] = useState(null);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState("");
  const [sendSuccess, setSendSuccess] = useState("");
  const [bulkRunning, setBulkRunning] = useState(false);
  const [bulkProgress, setBulkProgress] = useState(null);
  const [bulkMessage, setBulkMessage] = useState("");
  const bulkInFlight = useRef(false);

  const checkSession = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/auth/me`, {
        credentials: "include",
        cache: "no-store",
      });
      if (response.status === 401 || response.status === 403) {
        setAuthStatus("unauthenticated");
        return;
      }
      if (!response.ok) throw new Error(`Authentication check failed (${response.status})`);
      const data = await response.json();
      if (!data.authenticated) {
        setAuthStatus("unauthenticated");
        return;
      }
      setDirectorEmail(data.email || "");
      setAuthStatus("authenticated");
      setAuthError("");
    } catch (err) {
      setAuthError("Cannot contact the authentication server. Confirm FastAPI is running.");
      setAuthStatus("error");
    }
  }, []);

  useEffect(() => {
    checkSession();
  }, [checkSession]);

  const logout = async () => {
    setLoggingOut(true);
    setAuthError("");
    try {
      const response = await fetch(`${API_URL}/auth/logout`, {
        method: "POST",
        credentials: "include",
      });
      if (!response.ok) throw new Error(`Logout failed (${response.status})`);
      setSelectedDocument(null);
      setDocuments([]);
      setSignedDocuments([]);
      setDirectorEmail("");
      setAuthStatus("unauthenticated");
    } catch (err) {
      setAuthError("Unable to log out. Please try again.");
    } finally {
      setLoggingOut(false);
    }
  };

  const loadDocuments = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const response = await fetch(`${API_URL}/documents/pending?limit=500`, {
        credentials: "include",
        cache: "no-store",
      });
      if (response.status === 401 || response.status === 403) {
        setAuthStatus("unauthenticated");
        setDocuments([]);
        setSelectedDocument(null);
        return;
      }

      if (!response.ok) {
        throw new Error(`Server returned ${response.status}`);
      }

      const data = await response.json();
      setDocuments(data.documents || []);
      const archiveResponse = await fetch(`${API_URL}/documents/signed`, {
        credentials: "include", cache: "no-store",
      });
      if (!archiveResponse.ok) throw new Error(`Signed archive returned ${archiveResponse.status}`);
      const archive = await archiveResponse.json();
      setSignedDocuments(archive.documents || []);
    } catch (err) {
      console.error("Unable to load documents:", err);

      setError(
        "Unable to load documents. Confirm that the FastAPI backend is running."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (authStatus !== "authenticated") return;

    // Load immediately when the dashboard opens.
    loadDocuments();

    // Auto-refresh document lists every 5 minutes while the tab is visible.
    // The existing Refresh button still triggers loadDocuments() on demand.
    const interval = setInterval(() => {
      if (document.visibilityState === "visible") {
        loadDocuments();
      }
    }, 5 * 60 * 1000);

    return () => clearInterval(interval);
  }, [authStatus, loadDocuments]);

  // Read the independent year/month history when viewing it or changing year.
  const loadClearanceHistory = useCallback(async () => {
    if (authStatus !== "authenticated") return;
    setHistoryLoading(true);
    setHistoryError("");
    try {
      const response = await fetch(`${API_URL}/clearance-history?year=${historyYear}`, {
        credentials: "include", cache: "no-store",
      });
      if (!response.ok) throw new Error(`Cannot load clearance history (HTTP ${response.status})`);
      const data = await response.json();
      setClearanceHistory(data.members || []);
      const yearsResponse = await fetch(`${API_URL}/clearance-history/years`, {
        credentials: "include", cache: "no-store",
      });
      if (yearsResponse.ok) {
        const yearsData = await yearsResponse.json();
        setHistoryYears(yearsData.years || []);
      }
    } catch (err) {
      setHistoryError(err.message || "Unable to load clearance history.");
    } finally {
      setHistoryLoading(false);
    }
  }, [authStatus, historyYear]);

  useEffect(() => {
    if (view === "history") loadClearanceHistory();
  }, [view, loadClearanceHistory]);

  // Director-only soft removal: no old Gmail attachment can be re-imported.
  const removeDocument = async (document) => {
    if (!document || removingId !== null || bulkRunning || approving || sending) return;
    if (["sending", "send_unknown"].includes(document.status)) {
      setRemoveMessage("Delivery is unresolved; check Gmail Sent Mail before removing this document.");
      return;
    }
    const confirmed = window.confirm(
      `REMOVE THIS DOCUMENT FROM THE DASHBOARD?\n\n${document.filename}\n\n` +
      "This hides it from pending and signed lists. Signed PDFs, clearance history, " +
      "and audit records are retained. It will not be imported again."
    );
    if (!confirmed) return;
    setRemovingId(document.id);
    setRemoveMessage("");
    try {
      const response = await fetch(`${API_URL}/documents/${document.id}`, {
        method: "DELETE", credentials: "include",
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || `Removal failed (HTTP ${response.status})`);
      setRemoveMessage(`${document.filename} removed from the dashboard. Records retained.`);
      if (selectedDocument?.id === document.id) setSelectedDocument(null);
      if (signedDocument?.id === document.id) setSignedDocument(null);
      await loadDocuments();
      if (view === "history") await loadClearanceHistory();
    } catch (err) {
      setRemoveMessage(err.message || "Could not remove document.");
    } finally {
      setRemovingId(null);
    }
  };

  useEffect(() => {
    function handleKeyDown(event) {
      if (event.key === "Escape" && !approving) {
        setSelectedDocument(null);
      }
    }

    window.addEventListener("keydown", handleKeyDown);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [approving]);

  // Load the original PDF through the authenticated API and preview a local blob URL.
  // Revoke each URL when the modal closes to avoid retaining sensitive documents in memory.
  useEffect(() => {
    if (!selectedDocument || authStatus !== "authenticated") {
      setPdfBlobUrl("");
      setPdfError("");
      return;
    }
    let cancelled = false;
    let objectUrl = "";
    const controller = new AbortController();
    setPdfLoading(true);
    setPdfError("");
    setPdfBlobUrl("");
    (async () => {
      try {
        const response = await fetch(`${API_URL}/documents/${selectedDocument.id}/pdf`, {
          credentials: "include",
          cache: "no-store",
          signal: controller.signal,
        });
        if (response.status === 401 || response.status === 403) {
          if (!cancelled) setAuthStatus("unauthenticated");
          return;
        }
        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(
            errorData.detail ||
            `PDF request failed with HTTP status ${response.status}`
          );
        }
        const blob = await response.blob();
        if (cancelled) return;
        objectUrl = URL.createObjectURL(new Blob([blob], { type: "application/pdf" }));
        setPdfBlobUrl(objectUrl);
      } catch (err) {
        if (!cancelled && err.name !== "AbortError") {
          console.error("PDF Preview Error:", err);
          setPdfError(err.message || "Unable to load the PDF.");
        }
      } finally {
        if (!cancelled) setPdfLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [selectedDocument, authStatus]);

  useEffect(() => {
    return () => {
      if (signedPreviewUrl) URL.revokeObjectURL(signedPreviewUrl);
    };
  }, [signedPreviewUrl]);

  // One confirmed Director action signs the PDF and immediately sends it.
  // The backend performs the send itself after committing the signed copy,
  // preventing a lost browser connection between separate POST requests.
  const approveDocument = async () => {
    if (!selectedDocument || approving || bulkRunning) return;

    const documentToApprove = selectedDocument;
    const recipient = documentToApprove.sender_email?.trim();
    if (!recipient) {
      setApprovalError("Cannot approve and send: the original sender's email is missing.");
      return;
    }

    const confirmed = window.confirm(
      `APPROVE, SIGN AND EMAIL THIS DOCUMENT?\n\n` +
      `Document: ${documentToApprove.filename}\n` +
      `Recipient: ${recipient}\n\n` +
      "Click OK to apply the Director's protected signature and IMMEDIATELY " +
      "send the signed PDF by Gmail. No second confirmation will appear."
    );
    if (!confirmed) return;

    setApproving(true);
    setApprovalError("");
    setSendError("");
    setSendSuccess("");
    setSignedPreviewError("");
    setSignedPreviewUrl("");

    try {
      const response = await fetch(
        `${API_URL}/documents/${documentToApprove.id}/approve`,
        { method: "POST", credentials: "include" }
      );
      const result = await response.json().catch(() => ({}));

      if (response.status === 401 || response.status === 403) {
        setAuthStatus("unauthenticated");
        throw new Error("Your session has expired. Sign in again before approving.");
      }
      if (!response.ok) {
        throw new Error(result.detail || `Approval or email sending failed (${response.status}).`);
      }
      if (result.status !== "sent" || result.email_sent !== true) {
        throw new Error(
          "The request finished, but email delivery was not confirmed. " +
          "Check Gmail Sent Mail and the document archive before trying again."
        );
      }

      // A preview is optional: it must not delay or prevent the email send.
      setSendSuccess(`Approved, signed and sent to ${result.recipient || recipient}.`);
      setSignedDocument({ ...documentToApprove, status: "sent" });
      setSelectedDocument(null);
      await loadDocuments();

      try {
        const signedResponse = await fetch(
          `${API_URL}/documents/${documentToApprove.id}/signed-pdf`,
          { credentials: "include", cache: "no-store" }
        );
        if (!signedResponse.ok) throw new Error(`Preview request failed (${signedResponse.status})`);
        const blob = await signedResponse.blob();
        setSignedPreviewUrl(URL.createObjectURL(new Blob([blob], { type: "application/pdf" })));
      } catch (previewError) {
        setSignedPreviewError("Email sent successfully, but the signed PDF preview could not be loaded.");
      }
    } catch (err) {
      const message = err.message || "Unable to complete approval and sending.";
      // The server might have signed (or even sent) before a network error.
      // Read the saved status; never blindly repeat the approval or email.
      try {
        const statusResponse = await fetch(
          `${API_URL}/documents/${documentToApprove.id}`,
          { credentials: "include", cache: "no-store" }
        );
        if (statusResponse.ok) {
          const latest = await statusResponse.json();
          if (["signed", "sending", "send_unknown", "sent"].includes(latest.status)) {
            setSelectedDocument(null);
            setSignedDocument({ ...documentToApprove, ...latest });
            setSendError(
              `${message} Current status: ${latest.status}. ` +
              "Check the signed archive and Gmail Sent Mail before any manual retry."
            );
          } else {
            setApprovalError(message);
          }
        } else {
          setApprovalError(message);
        }
      } catch (statusError) {
        setApprovalError(message + " Check the archive and Gmail Sent Mail before trying again.");
      }
      await loadDocuments();
    } finally {
      setApproving(false);
    }
  };

  // Optional bulk route: ONE batch authorization, followed by the existing
  // Director-only approval endpoint for each pending document. Each endpoint
  // signs, saves and sends exactly one PDF. Nothing is signed on page load.
  const approveAllPending = async () => {
    if (bulkInFlight.current || bulkRunning || loading || approving || sending) return;

    const snapshot = documents.filter((doc) => doc.status === "pending_review");
    if (snapshot.length === 0) {
      setBulkMessage("There are no pending documents to approve.");
      return;
    }
    // The /documents/pending API returns a maximum of 500 items. Never claim
    // to approve *all* if the loaded list could have been truncated.
    if (snapshot.length >= 500) {
      setBulkMessage("The dashboard has reached its 500-document display limit. Bulk approval is disabled so that no documents are inadvertently omitted.");
      return;
    }
    if (snapshot.some((doc) => !doc.sender_email?.trim())) {
      setBulkMessage("Bulk approval is unavailable: one or more pending documents have no recipient email. Resolve those records first.");
      return;
    }

    const confirmed = window.confirm(
      `APPROVE, SIGN AND EMAIL ALL ${snapshot.length} PENDING DOCUMENTS?\n\n` +
      "This is one batch authorization. You will NOT preview each PDF. " +
      "Your protected Director signature will be applied to each document, " +
      "then each signed PDF will be emailed to its recorded original sender.\n\n" +
      "The documents are processed one at a time. Do not close this tab until " +
      "the batch completes. Failed or uncertain deliveries will not be retried automatically.\n\n" +
      "Press OK only if the Director authorizes all listed documents."
    );
    if (!confirmed) return;

    bulkInFlight.current = true;
    setBulkRunning(true);
    setBulkMessage("");
    setBulkProgress({ completed: 0, total: snapshot.length, sent: 0, failed: 0, needsAttention: 0 });
    let sent = 0;
    let failed = 0;
    let needsAttention = 0;
    let completed = 0;
    let stopReason = "";

    // Read the persisted status on any ambiguous HTTP/network outcome.
    const readStoredStatus = async (id) => {
      try {
        const response = await fetch(`${API_URL}/documents/${id}`, {
          credentials: "include",
          cache: "no-store",
        });
        return response.ok ? (await response.json()).status : null;
      } catch {
        return null;
      }
    };

    try {
      for (const doc of snapshot) {
        let shouldStop = false;
        try {
          const response = await fetch(`${API_URL}/documents/${doc.id}/approve`, {
            method: "POST",
            credentials: "include",
          });
          const result = await response.json().catch(() => ({}));

          if (response.ok && result.status === "sent" && result.email_sent === true) {
            sent += 1;
          } else {
            const latestStatus = await readStoredStatus(doc.id);
            if (latestStatus === "sent") {
              sent += 1; // The response may have been interrupted after Gmail confirmed.
            } else if (["signed", "sending", "send_unknown"].includes(latestStatus)) {
              needsAttention += 1;
              shouldStop = true;
              stopReason = `${doc.filename}: status is ${latestStatus}. Check the signed archive and Gmail Sent Mail before continuing.`;
            } else {
              failed += 1;
              const detail = typeof result.detail === "string" ? result.detail : `HTTP ${response.status}`;
              console.error("Bulk approval failed for document", doc.id, detail);
              // Authorization or Gmail-connection failures generally affect the entire batch.
              if ([401, 403, 503].includes(response.status) || latestStatus === null) {
                shouldStop = true;
                stopReason = `${doc.filename}: ${detail}. Batch stopped.`;
                if (response.status === 401 || response.status === 403) {
                  setAuthStatus("unauthenticated");
                }
              }
            }
          }
        } catch (err) {
          // An interrupted request could have *already sent* the email.
          // Never retry this document blindly.
          const latestStatus = await readStoredStatus(doc.id);
          if (latestStatus === "sent") {
            sent += 1;
          } else {
            needsAttention += 1;
            shouldStop = true;
            stopReason = `${doc.filename}: connection was interrupted (saved status: ${latestStatus || "unknown"}). Check Gmail Sent Mail and the archive.`;
          }
          console.error("Bulk approval request interrupted", doc.id, err);
        }

        completed += 1;
        setBulkProgress({ completed, total: snapshot.length, sent, failed, needsAttention });
        if (shouldStop) break;
      }
    } finally {
      bulkInFlight.current = false;
      setBulkRunning(false);
      setBulkMessage(
        `Batch finished: ${sent} sent, ${failed} failed, ${needsAttention} require attention. ` +
        `${snapshot.length - completed} not attempted.` +
        (stopReason ? ` ${stopReason}` : "")
      );
      await loadDocuments();
    }
  };

  const sendSignedDocument = async (document) => {
    if (!document || sending || document.status !== "signed") return;
    const recipient = document.sender_email;
    if (!recipient) {
      setSendError(`No recipient email is available for ${document.filename}.`);
      return;
    }
    const ok = window.confirm(
      `Send the signed PDF to ${recipient}?\n\n` +
      `Document: ${document.filename}\n\n` +
      "This sends a real email with the signed PDF attached. No PDF preview is required."
    );
    if (!ok) return;

    setSending(true);
    setSendError("");
    setSendSuccess("");
    try {
      const response = await fetch(`${API_URL}/documents/${document.id}/send`, {
        method: "POST", credentials: "include",
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || `Sending failed (${response.status})`);
      setSignedDocument((previous) =>
        previous?.id === document.id ? { ...previous, status: "sent" } : previous
      );
      setSendSuccess(`Gmail accepted the signed document for ${result.recipient || recipient}.`);
      await loadDocuments();
    } catch (err) {
      setSendError(`${document.filename}: ${err.message || "Unable to confirm delivery."} Check Gmail Sent Mail before retrying.`);
      await loadDocuments();
    } finally {
      setSending(false);
    }
  };

  const openSignedDocument = async (document) => {
    setSendError("");
    setSendSuccess("");
    setSignedDocument(document);
    setSignedPreviewError("");
    setSignedPreviewUrl("");
    try {
      const response = await fetch(`${API_URL}/documents/${document.id}/signed-pdf`, {
        credentials: "include", cache: "no-store",
      });
      if (!response.ok) throw new Error(`PDF request failed (${response.status})`);
      const blob = await response.blob();
      setSignedPreviewUrl(URL.createObjectURL(new Blob([blob], { type: "application/pdf" })));
    } catch (err) {
      setSignedPreviewError(err.message || "Could not open the signed PDF.");
    }
  };

  const displayedDocuments = view === "signed" ? signedDocuments : documents;
  const availableYears = [...new Set([
    new Date().getFullYear(),
    ...documents.map((doc) => doc.year),
    ...signedDocuments.map((doc) => doc.year),
  ].filter(Boolean))].sort((a, b) => b - a);
  const historyMonths = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"];
  const availableMonths = [...new Set(signedDocuments.map((doc) => doc.month).filter(Boolean))]
    .sort((a, b) => {
      const months = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"];
      return months.indexOf(String(a).toLowerCase()) - months.indexOf(String(b).toLowerCase());
    });
  const filteredDocuments = displayedDocuments.filter((document) => {
    const matchesMonth = view !== "signed" || selectedMonth === "all" || document.month === selectedMonth;
    const matchesYear = selectedYear === "all" || String(document.year) === selectedYear;
    const matchesFilter =
      filter === "all" || document.document_type === filter;

    const searchableText = [
      document.filename,
      document.state_code,
      document.sender_email,
      document.month,
      document.year,
      document.document_type,
    ]
      .join(" ")
      .toLowerCase();

    return matchesMonth && matchesYear && matchesFilter && searchableText.includes(search.toLowerCase());
  });

  const clearanceCount = documents.filter(
    (document) => document.document_type === "clearance"
  ).length;

  const paymentCount = documents.filter(
    (document) => document.document_type === "payment_approval"
  ).length;

  if (authStatus === "checking") {
    return (
      <div style={authStyles.page}>
        <div style={authStyles.card} role="status">
          <div style={authStyles.logo}>U</div>
          <h1>UHS Director Assistant</h1>
          <p>Checking your secure session…</p>
        </div>
      </div>
    );
  }

  if (authStatus !== "authenticated") {
    return (
      <div style={authStyles.page}>
        <div style={authStyles.card}>
          <div style={authStyles.logo}>U</div>
          <p style={authStyles.eyebrow}>DIRECTOR'S OFFICE</p>
          <h1 style={authStyles.heading}>UHS Director Assistant</h1>
          <p style={authStyles.description}>
            Securely review corps members' clearance and payment approval documents.
            Only the authorized Director can access this workspace.
          </p>
          {authError && <p role="alert" style={authStyles.error}>{authError}</p>}
          <a href={`${API_URL}/auth/login`} style={authStyles.loginButton}>
            Continue with Google
          </a>
          <button type="button" onClick={() => { setAuthStatus("checking"); checkSession(); }} style={authStyles.retryButton}>
            Check session again
          </button>
          <p style={authStyles.note}>Every signature requires the Director's explicit approval.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">U</div>

          <div>
            <h2>UHS Assistant</h2>
            <span>Director's Office</span>
          </div>
        </div>

        <div className="sidebar-label">WORKSPACE</div>

        <button
          className={`nav-item ${view === "pending" ? "active" : ""}`}
          type="button"
          onClick={() => {
            setView("pending");
            setFilter("all");
            setSearch("");
          }}
        >
          <span>▦</span> Dashboard
        </button>

        <button
          className="nav-item"
          type="button"
          onClick={() => {
            setView("pending");
            setFilter("all");
            setSearch("");
          }}
        >
          <span>▤</span> All pending documents
        </button>

        <button
          className={`nav-item ${view === "signed" ? "active" : ""}`}
          type="button"
          onClick={() => { setView("signed"); setFilter("all"); setSearch(""); }}
        >
          <span>✓</span> Signed documents by month
        </button>

        <button
          className={`nav-item ${view === "history" ? "active" : ""}`}
          type="button"
          onClick={() => { setView("history"); setSearch(""); setFilter("all"); }}
        >
          <span>▦</span> Annual clearance history
        </button>

        <div className="sidebar-label">DOCUMENT TYPES</div>

        <button
          className="nav-item"
          type="button"
          onClick={() => setFilter("clearance")}
        >
          <span>✓</span> Clearance
        </button>

        <button
          className="nav-item"
          type="button"
          onClick={() => setFilter("payment_approval")}
        >
          <span>▧</span> Payment approvals
        </button>

        <div className="sidebar-footer">
          <div className={`status-dot ${error ? "offline" : ""}`} />

          <div>
            <strong>Backend connection</strong>
            <span>{error ? "Connection issue" : "API reachable"}</span>
          </div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div>
            <div className="breadcrumb">Workspace / Dashboard</div>
            <h1>Director's Dashboard</h1>
          </div>

          <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontSize: 12, color: "#64748b" }} title="Authenticated Google account">
              {directorEmail}
            </span>
            <button className="refresh-button" onClick={loadDocuments} disabled={loading || bulkRunning} type="button">
              ↻ {loading ? "Refreshing…" : "Refresh"}
            </button>
            <button className="refresh-button" onClick={logout} disabled={loggingOut || bulkRunning} type="button">
              {loggingOut ? "Signing out…" : "Sign out"}
            </button>
          </div>
        </header>

        <section className="welcome-section">
          <div>
            <p className="eyebrow">DOCUMENT MANAGEMENT</p>
            <h2>Review and manage submissions</h2>

            <p>
              Inspect corps members' documents before authorizing any
              signature or email response.
            </p>
          </div>

          <div className="welcome-icon">▤</div>
        </section>

        <section
          aria-label="Bulk document approval"
          style={{
            padding: "18px 20px", marginBottom: 20, borderRadius: 12,
            background: "#f1f5fb", border: "1px solid #cbd8ee",
            display: "flex", flexWrap: "wrap", alignItems: "center", gap: 14,
          }}
        >
          <div style={{ flex: "1 1 270px" }}>
            <h2 style={{ margin: "0 0 6px", fontSize: 17, color: "#183c73" }}>
              Bulk document authorization
            </h2>
            <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5, color: "#475569" }}>
              Approve, sign and email all {documents.length} currently pending documents
              in one batch, without opening them. The individual Review buttons remain available.
            </p>
          </div>
          <button
            type="button"
            onClick={approveAllPending}
            disabled={bulkRunning || loading || approving || sending || documents.length === 0 || documents.length >= 500}
            style={{
              border: 0, borderRadius: 9, padding: "13px 18px", color: "white",
              background: "#183c73", fontWeight: 700, cursor: "pointer",
              opacity: (bulkRunning || loading || approving || sending || documents.length === 0 || documents.length >= 500) ? 0.55 : 1,
            }}
          >
            {bulkRunning
              ? `Processing ${bulkProgress?.completed ?? 0}/${bulkProgress?.total ?? documents.length}…`
              : `Approve, Sign & Send All (${documents.length})`}
          </button>
          {bulkProgress && (
            <p role="status" style={{ margin: 0, width: "100%", fontSize: 13, color: "#183c73" }}>
              Completed {bulkProgress.completed} of {bulkProgress.total} ·
              {" "}{bulkProgress.sent} sent · {bulkProgress.failed} failed ·
              {" "}{bulkProgress.needsAttention} require attention
            </p>
          )}
          {bulkMessage && (
            <p role="alert" style={{ margin: 0, width: "100%", fontSize: 13, color: "#944400" }}>
              {bulkMessage}
            </p>
          )}
        </section>

        {authError && <div className="error-banner" role="alert">{authError}</div>}

        {removeMessage && <div role="status" style={{ padding: 12, borderRadius: 8, background: "#edf5ff", color: "#123e71", marginBottom: 12 }}>{removeMessage}</div>}
        {sendError && <div className="error-banner" role="alert">{sendError}</div>}
        {sendSuccess && <div role="status" style={{ padding: 14, marginBottom: 16, background: "#edf8f0", color: "#176a3a", borderRadius: 8 }}>{sendSuccess}</div>}

        {error && (
          <div className="error-banner">
            {error}

            <button onClick={loadDocuments} type="button">
              Try again
            </button>
          </div>
        )}

        <section className="stats-grid">
          <article className="stat-card">
            <div className="stat-icon purple">▤</div>
            <p>Pending documents</p>
            <h3>{loading ? "—" : documents.length}</h3>
            <span>Awaiting review</span>
          </article>

          <article className="stat-card">
            <div className="stat-icon blue">✓</div>
            <p>Clearance documents</p>
            <h3>{loading ? "—" : clearanceCount}</h3>
            <span>Pending clearance review</span>
          </article>

          <article className="stat-card">
            <div className="stat-icon orange">▧</div>
            <p>Payment approvals</p>
            <h3>{loading ? "—" : paymentCount}</h3>
            <span>Pending payment review</span>
          </article>
        </section>

        {view === "history" ? (
          <section className="documents-panel">
            <div className="panel-heading">
              <div>
                <h2>Annual corps member clearance history</h2>
                <p>Completed and emailed clearances, by state code and month. A dash means no completed clearance is recorded.</p>
              </div>
              <span className="pending-badge">{clearanceHistory.filter((m) => m.state_code.toLowerCase().includes(search.toLowerCase())).length} corps members</span>
            </div>
            <div className="table-toolbar" style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                aria-label="Search clearance history by state code"
                placeholder="Search state code"
                style={{ border: "1px solid #d6dce4", padding: "10px 12px", borderRadius: 8 }}
              />
              <label htmlFor="history-year">Year</label>
              <select id="history-year" value={historyYear} onChange={(e) => setHistoryYear(Number(e.target.value))}>
                {[new Date().getFullYear() + 1, historyYear, ...availableYears, ...historyYears, new Date().getFullYear() - 1].filter((y,i,a) => a.indexOf(y) === i).sort((a,b) => b-a).map((year) => (
                  <option key={year} value={year}>{year}</option>
                ))}
              </select>
              <button type="button" className="refresh-button" onClick={loadClearanceHistory} disabled={historyLoading}>
                {historyLoading ? "Loading…" : "Refresh history"}
              </button>
            </div>
            {historyError && <div className="error-banner" role="alert">{historyError}</div>}
            <div className="table-container" style={{ overflowX: "auto" }}>
              <table style={{ minWidth: 1000 }}>
                <thead><tr><th>STATE CODE</th>{historyMonths.map((month) => (
                  <th key={month} title={month}>{month.slice(0, 3).toUpperCase()}</th>
                ))}</tr></thead>
                <tbody>
                  {historyLoading ? (
                    <tr><td colSpan="13" className="empty-state">Loading clearance history…</td></tr>
                  ) : clearanceHistory.length === 0 ? (
                    <tr><td colSpan="13" className="empty-state">No sent clearance records for {historyYear}.</td></tr>
                  ) : clearanceHistory.filter((m) => m.state_code.toLowerCase().includes(search.toLowerCase())).map((member) => (
                    <tr key={member.state_code}>
                      <td><span className="state-code">{member.state_code}</span></td>
                      {historyMonths.map((month) => (
                        <td key={month} title={member.months?.[month]?.cleared_at || "No recorded clearance"}>
                          {member.months?.[month] ? <span style={{ color: "#188451", fontWeight: 800 }}>✓</span> : "—"}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ) : (
        <section className="documents-panel">
          <div className="panel-heading">
            <div>
              <h2>{view === "signed" ? "Signed documents archive" : "Pending documents"}</h2>
              <p>
                {view === "signed" ? "Previously approved documents, organized by month" : "Documents retrieved from your connected Gmail workflow"}
              </p>
            </div>

            <span className="pending-badge">
              {filteredDocuments.length} document
              {filteredDocuments.length === 1 ? "" : "s"}
            </span>
          </div>

          <div className="table-toolbar">
            <div className="search-box">
              <span>⌕</span>

              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search state code, sender or filename"
                aria-label="Search documents"
              />
            </div>

            {view === "signed" && (
              <select
                value={selectedMonth}
                onChange={(event) => setSelectedMonth(event.target.value)}
                aria-label="Filter signed documents by month"
              >
                <option value="all">All months</option>
                {availableMonths.map((month) => (
                  <option key={month} value={month}>
                    {month.charAt(0).toUpperCase() + month.slice(1)}
                  </option>
                ))}
              </select>
            )}

            <select value={selectedYear} onChange={(event) => setSelectedYear(event.target.value)} aria-label="Filter documents by year">
              <option value="all">All years</option>
              {availableYears.map((year) => <option key={year} value={String(year)}>{year}</option>)}
            </select>

            <select
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              aria-label="Filter document type"
            >
              <option value="all">All document types</option>
              <option value="clearance">Clearance</option>
              <option value="payment_approval">Payment approval</option>
            </select>
          </div>

          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>DOCUMENT</th>
                  <th>STATE CODE</th>
                  <th>MONTH</th>
                  <th>YEAR</th>
                  <th>SUBMITTED BY</th>
                  <th>DATE RECEIVED</th>
                  <th>STATUS</th>
                  <th>ACTION</th>
                </tr>
              </thead>

              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan="8" className="empty-state">
                      Loading documents from the database…
                    </td>
                  </tr>
                ) : filteredDocuments.length === 0 ? (
                  <tr>
                    <td colSpan="8" className="empty-state">
                      {view === "signed" ? "No signed documents match this month or search." : "No pending documents match your search."}
                    </td>
                  </tr>
                ) : (
                  filteredDocuments.map((document) => (
                    <tr key={document.id}>
                      <td>
                        <div className="document-cell">
                          <div className="pdf-icon">PDF</div>

                          <div>
                            <strong>
                              {formatDocumentType(document.document_type)}
                            </strong>
                            <span>{document.filename}</span>
                          </div>
                        </div>
                      </td>

                      <td>
                        <span className="state-code">
                          {document.state_code || "—"}
                        </span>
                      </td>

                      <td className="month-cell">
                        {document.month
                          ? document.month.charAt(0).toUpperCase() +
                            document.month.slice(1)
                          : "—"}
                      </td>

                      <td>{document.year || "—"}</td>

                      <td className="sender-cell">
                        {document.sender_email || "—"}
                      </td>

                      <td className="date-cell">
                        {formatDate(document.created_at)}
                      </td>

                      <td>
                        <span className="status-pill">
                          <span />
                          {view === "signed" ? (document.status === "sent" ? "Sent" : "Signed") : "Pending review"}
                        </span>
                      </td>

                      <td>
                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                          <button
                            className="review-button"
                            type="button"
                            onClick={() => view === "signed" ? openSignedDocument(document) : setSelectedDocument(document)}
                              disabled={bulkRunning}
                          >
                            {view === "signed" ? "View signed PDF" : "Review"}
                          </button>
                          <button
                            type="button"
                            className="review-button"
                            disabled={bulkRunning || approving || sending || removingId !== null || ["sending", "send_unknown"].includes(document.status)}
                            title="Remove from dashboard; retain audit history and signed PDF"
                            onClick={() => removeDocument(document)}
                            style={{ background: "#fff2f2", color: "#a62727", border: "1px solid #eec7c7" }}
                          >
                            {removingId === document.id ? "Removing…" : "Remove"}
                          </button>
                          {view === "signed" && document.status === "signed" && (
                            <button
                              type="button"
                              className="review-button"
                              disabled={bulkRunning || sending || !document.sender_email}
                              title={!document.sender_email ? "Recipient email is missing" : "Send signed PDF without opening preview"}
                              onClick={() => sendSignedDocument(document)}
                              style={{ background: "#183c73", color: "#fff", border: 0 }}
                            >
                              {sending ? "Please wait…" : "Send to Corps Member"}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
        )}

        <footer className="page-footer">
          <span>UHS Director Assistant</span>
          <span>
            All signatures require explicit Director approval.
          </span>
        </footer>
      </main>

      {signedDocument && (
        <div className="modal-backdrop" role="presentation">
          <section className="review-modal" role="dialog" aria-modal="true" aria-labelledby="signed-title">
            <div className="modal-heading">
              <div>
                <p className="eyebrow">APPROVAL COMPLETED</p>
                <h2 id="signed-title">Signed PDF ready for review</h2>
              </div>
              <button className="close-button" type="button" aria-label="Close signed preview"
                onClick={() => { setSignedDocument(null); setSignedPreviewUrl(""); }}>×</button>
            </div>
            <p>Signed copy of <strong>{signedDocument.filename}</strong>.
              Viewing this PDF does not send an email.</p>
            <p><strong>Recipient:</strong> {signedDocument.sender_email || "Unavailable"}</p>
            <p><strong>Delivery:</strong> {signedDocument.status === "sent" ? "Already sent" : signedDocument.status === "send_unknown" ? "Delivery unconfirmed — check Gmail Sent Mail" : signedDocument.status === "sending" ? "Sending in progress" : "Not yet sent"}</p>
            {sendError && <p role="alert" style={{ color: "#a52222" }}>{sendError}</p>}
            {sendSuccess && <p role="status" style={{ color: "#176a3a" }}>{sendSuccess}</p>}
            {signedDocument.status === "signed" && (
              <div style={{ margin: "16px 0", display: "grid", gap: 8 }}>
                <button
                  type="button"
                  disabled={bulkRunning || sending || !signedDocument.sender_email || !signedPreviewUrl || Boolean(signedPreviewError)}
                  onClick={() => sendSignedDocument(signedDocument)}
                  style={{ background: "#183c73", color: "white", border: 0, borderRadius: 8, padding: "12px 18px", fontWeight: 700, cursor: "pointer", opacity: (!signedDocument.sender_email || !signedPreviewUrl || signedPreviewError) ? 0.55 : 1 }}
                >
                  {sending ? "Sending…" : "Send to Corps Member"}
                </button>
                {!signedDocument.sender_email && (
                  <p role="alert">Sending is unavailable because the original sender's email address is missing.</p>
                )}
                {!signedPreviewUrl && !signedPreviewError && (
                  <p role="status">Loading signed PDF. Sending will be available once the PDF is ready.</p>
                )}
                {signedPreviewError && (
                  <p role="alert">Sending is disabled until the signed PDF can be loaded. Close this window and try opening the document again.</p>
                )}
              </div>
            )}
            {signedDocument.status !== "signed" && signedDocument.status !== "sent" && (
              <p role="status">Sending is unavailable while the document's delivery status is {signedDocument.status || "unknown"}.</p>
            )}
            {signedPreviewError && <p role="alert">{signedPreviewError}</p>}
            {signedPreviewUrl && (
              <>
                <iframe className="pdf-preview-frame" src={signedPreviewUrl}
                  title={`Signed PDF: ${signedDocument.filename}`} />
                <a href={signedPreviewUrl} target="_blank" rel="noopener noreferrer">
                  Open signed PDF
                </a>
              </>
            )}
            <button className="close-modal-button" type="button"
              onClick={() => { setSignedDocument(null); setSignedPreviewUrl(""); }}>
              Close
            </button>
          </section>
        </div>
      )}

      {selectedDocument && (
        <div
          className="modal-backdrop"
          onClick={() => { if (!approving) setSelectedDocument(null); }}
          role="presentation"
        >
          <section
            className="review-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="review-title"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-heading">
              <div>
                <p className="eyebrow">DOCUMENT REVIEW</p>
                <h2 id="review-title">Review submission</h2>
              </div>

              <button
                className="close-button"
                onClick={() => setSelectedDocument(null)}
                type="button"
                aria-label="Close review"
              >
                ×
              </button>
            </div>

            <dl className="details-list">
              <div>
                <dt>Filename</dt>
                <dd>{selectedDocument.filename}</dd>
              </div>

              <div>
                <dt>Document type</dt>
                <dd>
                  {formatDocumentType(selectedDocument.document_type)}
                </dd>
              </div>

              <div>
                <dt>State code</dt>
                <dd>{selectedDocument.state_code || "—"}</dd>
              </div>

              <div>
                <dt>Month</dt>
                <dd>{selectedDocument.month || "—"}</dd>
              </div>

              <div>
                <dt>Sender</dt>
                <dd>{selectedDocument.sender_email || "—"}</dd>
              </div>

              <div>
                <dt>Received</dt>
                <dd>{formatDate(selectedDocument.created_at)}</dd>
              </div>
            </dl>

            <section className="pdf-preview-section">
              <div className="pdf-preview-heading">
                <div className="pdf-preview-title">
                  <div className="pdf-preview-icon">
                    <svg
                      width="21"
                      height="21"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden="true"
                    >
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                      <path d="M14 2v6h6" />
                      <path d="M8 13h8" />
                      <path d="M8 17h8" />
                    </svg>
                  </div>

                  <div>
                    <h3>Original PDF</h3>
                    <p>Review the full document before approval.</p>
                  </div>
                </div>

                <a
                  className="open-pdf-link"
                  href={pdfBlobUrl || undefined}
                  target="_blank"
                  rel="noopener noreferrer"
                  title="Open the original PDF in a new browser tab"
                  onClick={(event) => { if (!pdfBlobUrl) event.preventDefault(); }}
                  aria-disabled={!pdfBlobUrl}
                >
                  <svg
                    width="17"
                    height="17"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <path d="M14 3h7v7" />
                    <path d="M10 14 21 3" />
                    <path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5" />
                  </svg>

                  <span>Open PDF</span>

                  <span className="open-pdf-external" aria-hidden="true">
                    ↗
                  </span>
                </a>
              </div>

              {pdfLoading && <p role="status">Loading secure PDF preview…</p>}
              {pdfError && <p role="alert">{pdfError}</p>}
              {pdfBlobUrl && (
                <iframe
                  key={selectedDocument.id}
                  className="pdf-preview-frame"
                  src={pdfBlobUrl}
                  title={`PDF preview: ${selectedDocument.filename}`}
                />
              )}
            </section>

            <div className="review-notice">
              <strong>Director approval required</strong>
              <p>
                Approving applies the Director's authentic signature in the designated
                Director signature space, then immediately emails the signed PDF
                to the original sender. Confirm the recipient before proceeding.
              </p>
            </div>
            {approvalError && <p role="alert" style={{ color: "#a52222" }}>{approvalError}</p>}
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", justifyContent: "flex-end" }}>
              <button
                className="close-modal-button"
                onClick={() => setSelectedDocument(null)}
                type="button"
                disabled={approving}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={approveDocument}
                disabled={approving || bulkRunning || pdfLoading || !pdfBlobUrl}
                style={{ background: "#183c73", color: "#fff", border: 0, borderRadius: 8, padding: "12px 18px", fontWeight: 700, cursor: "pointer" }}
              >
                {approving ? "Signing and emailing…" : "Approve, Sign & Send"}
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

export default App;

const authStyles = {
  page: { minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#f5f7fb", padding: 24, fontFamily: "Inter, system-ui, sans-serif" },
  card: { background: "white", width: "100%", maxWidth: 460, borderRadius: 18, padding: "42px 36px", boxShadow: "0 18px 55px rgba(24, 39, 75, 0.10)", textAlign: "center" },
  logo: { background: "#183c73", color: "white", width: 54, height: 54, borderRadius: 14, display: "grid", placeItems: "center", fontSize: 30, fontWeight: 800, margin: "0 auto 22px" },
  eyebrow: { fontSize: 11, fontWeight: 800, letterSpacing: 2, color: "#3b65a0" },
  heading: { color: "#142d50", fontSize: 27, margin: "8px 0 14px" },
  description: { color: "#65748a", fontSize: 14, lineHeight: 1.7, marginBottom: 30 },
  loginButton: { display: "block", background: "#183c73", color: "white", textDecoration: "none", padding: "14px 20px", borderRadius: 9, fontWeight: 700 },
  retryButton: { border: 0, background: "transparent", color: "#315b93", cursor: "pointer", marginTop: 18, fontWeight: 600 },
  note: { color: "#8290a1", fontSize: 12, marginTop: 30 },
  error: { background: "#fff0f0", color: "#9b1c1c", padding: 12, borderRadius: 8, fontSize: 13 },
};
