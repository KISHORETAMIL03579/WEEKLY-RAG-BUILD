import React, { useState, useEffect, useRef, useCallback } from "react";
import { DocumentInfo, StagedFile } from "../types/document";
import { ToastContainer, ToastItem } from "../components/common/ToastContainer";
import { Topbar } from "../components/common/Topbar";
import { Sidebar } from "../components/Sidebar/Sidebar";
import { ChatArea, ChatMessage } from "../components/Chat/ChatArea";
import { api } from "../services/api";
import { generateId } from "../utils/helpers";

export const ChatPage: React.FC = () => {
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(() =>
    typeof window !== "undefined" ? window.innerWidth > 700 : true,
  );
  const [backendMode, setBackendMode] = useState<string>("");
  const [backendStatus, setBackendStatus] = useState<
    "checking" | "healthy" | "error"
  >("checking");
  const [retrievalMode, setRetrievalMode] = useState<string>("hybrid");
  const [files, setFiles] = useState<DocumentInfo[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<StagedFile[]>([]);
  const [strategy, setStrategy] = useState<string>("structured");
  const [strategySelected, setStrategySelected] = useState<boolean>(false);
  const [topK, setTopK] = useState<number>(8);
  const [temperature, setTemperature] = useState<number>(0.0);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [isThinking, setIsThinking] = useState<boolean>(false);
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const activeAbortControllerRef = useRef<AbortController | null>(null);
  const activeChatRunIdRef = useRef<string | null>(null);
  const isMountedRef = useRef(true);
  const toastTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(
    new Map(),
  );
  const selectedFilesRef = useRef<StagedFile[]>(selectedFiles);

  useEffect(() => {
    selectedFilesRef.current = selectedFiles;
  }, [selectedFiles]);

  const dismissToast = useCallback((id: string) => {
    if (toastTimersRef.current.has(id)) {
      clearTimeout(toastTimersRef.current.get(id));
      toastTimersRef.current.delete(id);
    }
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showToast = useCallback(
    (
      message: string,
      type: "info" | "success" | "error" = "info",
      duration = 5000,
    ) => {
      const id = generateId("toast");
      setToasts((prev) => [...prev, { id, message, type }]);
      if (duration > 0) {
        const timer = setTimeout(() => {
          dismissToast(id);
        }, duration);
        toastTimersRef.current.set(id, timer);
      }
    },
    [dismissToast],
  );

  // Clean up all toast timers on component unmount
  useEffect(() => {
    return () => {
      toastTimersRef.current.forEach((timer) => clearTimeout(timer));
      toastTimersRef.current.clear();
    };
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      const controller = activeAbortControllerRef.current;
      const runId = activeChatRunIdRef.current;
      activeAbortControllerRef.current = null;
      activeChatRunIdRef.current = null;
      controller?.abort();
      if (runId) {
        void api.cancelAsk(runId).catch((err: unknown) => {
          console.warn("Could not cancel chat run during navigation:", err);
        });
      }
    };
  }, []);

  // Display toast after browser hard refresh
  useEffect(() => {
    const HARD_REFRESH_TOAST_KEY = "ask-my-docs-hard-refresh";
    try {
      if (sessionStorage.getItem(HARD_REFRESH_TOAST_KEY) === "1") {
        sessionStorage.removeItem(HARD_REFRESH_TOAST_KEY);
        const timer = setTimeout(() => {
          showToast(
            "↻ Hard refresh completed. Latest resources loaded.",
            "success",
            3500,
          );
        }, 300);
        return () => clearTimeout(timer);
      }
    } catch {
      // Gracefully handle restricted storage
    }
  }, [showToast]);

  // Global key listener to detect hard refresh
  useEffect(() => {
    const HARD_REFRESH_TOAST_KEY = "ask-my-docs-hard-refresh";
    const handleKeyDown = (event: KeyboardEvent) => {
      const isHardRefresh =
        (event.shiftKey &&
          (event.ctrlKey || event.metaKey) &&
          event.key &&
          event.key.toLowerCase() === "r") ||
        ((event.ctrlKey || event.shiftKey) &&
          (event.key === "F5" || event.code === "F5"));

      if (isHardRefresh) {
        try {
          sessionStorage.setItem(HARD_REFRESH_TOAST_KEY, "1");
        } catch {
          // Gracefully handle storage errors
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  // Staged files lifecycle management with preview URLs
  const handleAddSelectedFiles = useCallback((rawFiles: File[]) => {
    const newItems: StagedFile[] = rawFiles.map((file) => ({
      id: generateId("staged"),
      file,
      name: file.name,
      previewUrl:
        typeof URL !== "undefined" && typeof URL.createObjectURL === "function"
          ? URL.createObjectURL(file)
          : null,
    }));
    setSelectedFiles((prev) => [...prev, ...newItems]);
  }, []);

  const handleRemoveSelectedFile = useCallback((idToRemove: string) => {
    setSelectedFiles((prev) => {
      const target = prev.find((item) => item.id === idToRemove);
      if (
        target &&
        target.previewUrl &&
        typeof URL !== "undefined" &&
        typeof URL.revokeObjectURL === "function"
      ) {
        URL.revokeObjectURL(target.previewUrl);
      }
      return prev.filter((item) => item.id !== idToRemove);
    });
  }, []);

  const handleClearSelectedFiles = useCallback(() => {
    setSelectedFiles((prev) => {
      prev.forEach((item) => {
        if (
          item.previewUrl &&
          typeof URL !== "undefined" &&
          typeof URL.revokeObjectURL === "function"
        ) {
          URL.revokeObjectURL(item.previewUrl);
        }
      });
      return [];
    });
  }, []);

  // Cleanup all staged URLs on component unmount
  useEffect(() => {
    return () => {
      selectedFilesRef.current.forEach((item) => {
        if (
          item.previewUrl &&
          typeof URL !== "undefined" &&
          typeof URL.revokeObjectURL === "function"
        ) {
          URL.revokeObjectURL(item.previewUrl);
        }
      });
    };
  }, []);

  const fetchStatus = useCallback(async () => {
    try {
      const status = await api.getStatus();
      setFiles(status.documents || []);
      if (status.vector_backend) setBackendMode(status.vector_backend);
      if (status.mode) setRetrievalMode(status.mode);
      setBackendStatus("healthy");
    } catch (err: unknown) {
      const e = err as Error;
      console.error("Failed to fetch status:", e);
      setBackendStatus("error");
      showToast(
        "Could not connect to backend server: " + e.message,
        "error",
        6000,
      );
    }
  }, [showToast]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  // Synchronize Sidebar with Viewport Resize
  useEffect(() => {
    const mql = window.matchMedia("(max-width: 700px)");
    const handleMediaChange = (e: MediaQueryListEvent) => {
      if (e.matches) {
        setSidebarOpen(false);
      } else {
        setSidebarOpen(true);
      }
    };

    if (mql.addEventListener) {
      mql.addEventListener("change", handleMediaChange);
    } else {
      mql.addListener(handleMediaChange);
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && sidebarOpen && window.innerWidth <= 700) {
        setSidebarOpen(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);

    return () => {
      if (mql.removeEventListener) {
        mql.removeEventListener("change", handleMediaChange);
      } else {
        mql.removeListener(handleMediaChange);
      }
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [sidebarOpen]);

  const handleUpload = async (stagedList: StagedFile[]) => {
    if (!stagedList || stagedList.length === 0 || isThinking || isUploading)
      return;
    setIsUploading(true);
    const formData = new FormData();
    stagedList.forEach((item) => formData.append("files", item.file));
    formData.append("chunk_mode", strategy);

    try {
      const res = await api.uploadFiles(formData);
      handleClearSelectedFiles();
      await fetchStatus();
      const failed = (res.documents || []).filter((d) => d.error);
      const degraded = (res.documents || []).filter((d) => d.warning);
      if (failed.length > 0) {
        showToast(
          `${failed.length} file(s) failed: ${failed.map((d) => d.filename + " (" + d.error + ")").join(", ")}`,
          "error",
          7000,
        );
      } else if (degraded.length > 0) {
        showToast(
          `${degraded.length} file(s) indexed with warnings: ${degraded.map((d) => d.filename).join(", ")}`,
          "info",
          6000,
        );
      } else {
        showToast(
          "Documents uploaded and indexed successfully!",
          "success",
          4000,
        );
      }
    } catch (err: unknown) {
      const e = err as Error;
      showToast("Upload failed: " + e.message, "error", 6000);
    } finally {
      setIsUploading(false);
    }
  };

  const handleLoadUrl = async (url: string) => {
    if (isThinking || isUploading) return;
    try {
      await api.loadUrl(url, strategy);
      await fetchStatus();
      showToast("Web page fetched and indexed successfully!", "success", 4000);
    } catch (err: unknown) {
      const e = err as Error;
      showToast("Failed to load URL: " + e.message, "error", 6000);
    }
  };

  const handleRemoveDoc = async (doc_id: string) => {
    if (isThinking || isUploading) return;
    try {
      await api.removeDoc(doc_id);
      await fetchStatus();
      showToast("Document removed from index.", "info", 3000);
    } catch (err: unknown) {
      const e = err as Error;
      showToast("Failed to remove document: " + e.message, "error", 6000);
    }
  };

  const handleClear = async () => {
    if (isThinking || isUploading) return;
    try {
      const response = await api.clearSession();
      setMessages([]);
      await fetchStatus();
      if (response.warning) {
        showToast(response.warning, "error", 6000);
      } else {
        showToast("All documents and chat history cleared.", "info", 3000);
      }
    } catch (err: unknown) {
      const e = err as Error;
      showToast("Failed to clear documents: " + e.message, "error", 6000);
    }
  };

  const handleStop = () => {
    const controller = activeAbortControllerRef.current;
    if (!controller) return;
    const runId = activeChatRunIdRef.current;
    activeAbortControllerRef.current = null;
    activeChatRunIdRef.current = null;
    controller.abort();
    setIsThinking(false);
    if (runId) {
      void api.cancelAsk(runId).catch((err: unknown) => {
        const error = err as Error;
        if (isMountedRef.current) {
          showToast(
            "Could not cancel the active request: " + error.message,
            "error",
          );
        }
      });
    }
  };

  const handleSend = async (query: string, existingTurnId?: string) => {
    if (activeAbortControllerRef.current || isUploading) return;
    const turnId = existingTurnId || generateId("turn");
    const runId = generateId("run");
    const userMessageId = generateId("user-msg");
    const assistantMessageId = generateId("ai-msg");
    const controller = new AbortController();
    activeAbortControllerRef.current = controller;
    activeChatRunIdRef.current = runId;

    setMessages((previous) => {
      const hasTurn = previous.some(
        (message) => message.role === "user" && message.turnId === turnId,
      );
      if (!hasTurn) {
        return [
          ...previous,
          { id: userMessageId, turnId, role: "user", text: query },
        ];
      }
      return previous.map((message) =>
        message.role === "user" && message.turnId === turnId
          ? { ...message, text: query }
          : message,
      );
    });
    setIsThinking(true);

    try {
      const res = await api.askQuestion(
        query,
        strategy,
        topK,
        temperature,
        controller.signal,
        turnId,
        runId,
      );
      if (controller.signal.aborted) return;
      const aiMsg: ChatMessage = {
        id: assistantMessageId,
        turnId,
        role: "ai",
        text: res.answer || "I don't know.",
        sources: res.sources || [],
        query,
        runId: res.run_id || res.trace_id,
        topK: res.top_k != null ? res.top_k : topK,
        temperature: res.temperature != null ? res.temperature : temperature,
      };
      setMessages((previous) => {
        const existingIndex = previous.findIndex(
          (message) => message.role === "ai" && message.turnId === turnId,
        );
        if (existingIndex === -1) return [...previous, aiMsg];
        return previous.map((message, index) =>
          index === existingIndex ? { ...aiMsg, id: message.id } : message,
        );
      });
    } catch (err: unknown) {
      const e = err as Error;
      if (controller.signal.aborted || e.name === "AbortError") return;
      const errorMessage: ChatMessage = {
        id: assistantMessageId,
        turnId,
        role: "ai",
        text: "Error executing query: " + e.message,
        query,
        topK,
        temperature,
      };
      setMessages((previous) => {
        const existingIndex = previous.findIndex(
          (message) => message.role === "ai" && message.turnId === turnId,
        );
        if (existingIndex === -1) return [...previous, errorMessage];
        return previous.map((message, index) =>
          index === existingIndex
            ? { ...errorMessage, id: message.id }
            : message,
        );
      });
      showToast("Query error: " + e.message, "error", 6000);
    } finally {
      if (activeAbortControllerRef.current === controller) {
        activeAbortControllerRef.current = null;
        activeChatRunIdRef.current = null;
        setIsThinking(false);
      }
    }
  };

  return (
    <div className={`layout ${sidebarOpen ? "" : "sidebar-collapsed"}`}>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <Topbar
        backendMode={backendMode}
        backendStatus={backendStatus}
        docsCount={files.length}
        retrievalMode={retrievalMode}
        topK={topK}
        temperature={temperature}
        sidebarOpen={sidebarOpen}
        onToggleSidebar={() => setSidebarOpen((v) => !v)}
      />
      <div
        className="sidebar-backdrop"
        onClick={() => setSidebarOpen(false)}
        aria-hidden="true"
      />
      <Sidebar
        strategy={strategy}
        setStrategy={setStrategy}
        setStrategySelected={setStrategySelected}
        topK={topK}
        setTopK={setTopK}
        temperature={temperature}
        setTemperature={setTemperature}
        files={files}
        onUpload={handleUpload}
        onLoadUrl={handleLoadUrl}
        onRemoveDoc={handleRemoveDoc}
        onClear={handleClear}
        isUploading={isUploading}
        isThinking={isThinking}
        selectedFiles={selectedFiles}
        onAddSelectedFiles={handleAddSelectedFiles}
        onRemoveSelectedFile={handleRemoveSelectedFile}
        onClearSelectedFiles={handleClearSelectedFiles}
      />
      <ChatArea
        messages={messages}
        onSend={handleSend}
        onStop={handleStop}
        isThinking={isThinking}
        filesCount={files.length}
        selectedFilesCount={selectedFiles.length}
        strategy={strategy}
        strategySelected={strategySelected}
      />
    </div>
  );
};
