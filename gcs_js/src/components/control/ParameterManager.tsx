/** Parameter fetch, search, missing-index retry, and confirmed write UI. */

"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { UAV_AGENT_BY_ID } from "@/config/agents";
import { useWebSocket } from "@/hooks/useWebSocket";
import {
  fetchParameterSnapshot,
  getControlWebSocketUrl,
  retryMissingParameters,
  setParameter,
  startParameterFetch,
} from "@/lib/controlApi";
import type {
  ControlWebSocketEvent,
  ParamFetchProgress,
  ParamSetResponse,
  ParamSnapshot,
  ParamValue,
} from "@/types/control";
import type { UAVId } from "@/types/telemetry";
import { UavSelector } from "./UavSelector";

const PAGE_SIZE = 100;

interface PendingParamChange {
  parameter: ParamValue;
  nextValue: number;
}

function emptyProgress(slot: UAVId): ParamFetchProgress {
  return {
    slot,
    status: "idle",
    received: 0,
    total: 0,
    missing_indices: [],
  };
}

function parseControlEvent(payload: string): ControlWebSocketEvent | null {
  try {
    return JSON.parse(payload) as ControlWebSocketEvent;
  } catch {
    return null;
  }
}

export function ParameterManager() {
  const [slot, setSlot] = useState<UAVId>(1);
  const [parameters, setParameters] = useState<ParamValue[]>([]);
  const [progress, setProgress] = useState<ParamFetchProgress>(
    emptyProgress(1),
  );
  const [searchInput, setSearchInput] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [page, setPage] = useState(0);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [isStartingFetch, setIsStartingFetch] = useState(false);
  const [savingParamId, setSavingParamId] = useState<string | null>(null);
  const [pendingChange, setPendingChange] =
    useState<PendingParamChange | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const snapshotGeneration = useRef(0);

  const agent = UAV_AGENT_BY_ID[slot];

  const applySnapshot = useCallback((snapshot: ParamSnapshot) => {
    setParameters(snapshot.parameters);
    setProgress(snapshot);
    setEdits(Object.fromEntries(
      snapshot.parameters.map((parameter) => [
        parameter.param_id,
        String(parameter.value),
      ]),
    ));
  }, []);

  const refreshSnapshot = useCallback(async () => {
    const generation = snapshotGeneration.current;
    try {
      const snapshot = await fetchParameterSnapshot(slot);
      if (generation !== snapshotGeneration.current) return;
      applySnapshot(snapshot);
      setError(null);
    } catch (snapshotError) {
      if (generation !== snapshotGeneration.current) return;
      setError(
        snapshotError instanceof Error
          ? snapshotError.message
          : "Parameter snapshot failed.",
      );
    } finally {
      if (generation === snapshotGeneration.current) {
        setIsLoading(false);
      }
    }
  }, [applySnapshot, slot]);

  useEffect(() => {
    let active = true;
    fetchParameterSnapshot(slot)
      .then((snapshot) => {
        if (!active) return;
        applySnapshot(snapshot);
        setError(null);
      })
      .catch((snapshotError: unknown) => {
        if (!active) return;
        setError(
          snapshotError instanceof Error
            ? snapshotError.message
            : "Parameter snapshot failed.",
        );
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [applySnapshot, slot]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearchTerm(searchInput.trim().toUpperCase());
      setPage(0);
    }, 180);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const handleControlMessage = useCallback(
    (payload: string) => {
      const event = parseControlEvent(payload);
      if (!event || event.slot !== slot) return;

      if (event.type === "param_snapshot") {
        applySnapshot(event);
        setIsLoading(false);
      } else if (
        event.type === "param_fetch_progress"
        || event.type === "param_fetch_complete"
      ) {
        setProgress(event);
        if (event.type === "param_fetch_complete") {
          void refreshSnapshot();
        }
      } else if (event.type === "param_set_result") {
        const confirmed = event.confirmed_value;
        if (confirmed !== null && confirmed !== undefined) {
          setParameters((current) => current.map((parameter) =>
            parameter.param_id === event.param_id
              ? { ...parameter, value: confirmed }
              : parameter
          ));
          setEdits((current) => ({
            ...current,
            [event.param_id]: String(confirmed),
          }));
        }
      }
    },
    [applySnapshot, refreshSnapshot, slot],
  );

  useWebSocket({
    url: getControlWebSocketUrl(slot),
    onMessage: handleControlMessage,
  });

  const filteredParameters = useMemo(
    () => (
      searchTerm
        ? parameters.filter((parameter) =>
            parameter.param_id.includes(searchTerm)
          )
        : parameters
    ),
    [parameters, searchTerm],
  );
  const totalPages = Math.max(
    1,
    Math.ceil(filteredParameters.length / PAGE_SIZE),
  );
  const visibleParameters = filteredParameters.slice(
    page * PAGE_SIZE,
    (page + 1) * PAGE_SIZE,
  );
  const busy = progress.status === "fetching"
    || progress.status === "retrying"
    || isStartingFetch;
  const progressPercent = progress.total
    ? Math.min(100, Math.round((progress.received / progress.total) * 100))
    : 0;

  const changeSlot = (nextSlot: UAVId) => {
    snapshotGeneration.current += 1;
    setSlot(nextSlot);
    setIsLoading(true);
    setParameters([]);
    setProgress(emptyProgress(nextSlot));
    setEdits({});
    setSearchInput("");
    setSearchTerm("");
    setPage(0);
    setError(null);
    setNotice(null);
  };

  const handleFetchAll = async () => {
    setIsStartingFetch(true);
    setError(null);
    setNotice(null);
    setProgress((current) => ({ ...current, status: "fetching" }));
    try {
      await startParameterFetch(slot);
      setNotice(`Parameter fetch started for ${agent.shortLabel}.`);
    } catch (fetchError) {
      setProgress((current) => ({ ...current, status: "error" }));
      setError(
        fetchError instanceof Error
          ? fetchError.message
          : "Unable to start parameter fetch.",
      );
    } finally {
      setIsStartingFetch(false);
    }
  };

  const handleRetryMissing = async () => {
    setError(null);
    setNotice(null);
    setProgress((current) => ({ ...current, status: "retrying" }));
    try {
      await retryMissingParameters(slot);
      setNotice(
        `Retrying ${progress.missing_indices.length} missing indices.`,
      );
    } catch (retryError) {
      setProgress((current) => ({ ...current, status: "error" }));
      setError(
        retryError instanceof Error
          ? retryError.message
          : "Unable to retry missing parameters.",
      );
    }
  };

  const requestSave = (parameter: ParamValue) => {
    const nextValue = Number(edits[parameter.param_id]);
    if (!Number.isFinite(nextValue)) {
      setError(`${parameter.param_id} requires a finite numeric value.`);
      return;
    }
    if (nextValue === parameter.value) {
      setNotice(`${parameter.param_id} has not changed.`);
      return;
    }
    setPendingChange({ parameter, nextValue });
    setError(null);
    setNotice(null);
  };

  const confirmSave = async () => {
    if (!pendingChange) return;
    const { parameter, nextValue } = pendingChange;
    setSavingParamId(parameter.param_id);
    setError(null);
    try {
      const response: ParamSetResponse = await setParameter(
        slot,
        parameter.param_id,
        {
          value: nextValue,
          param_type: parameter.type,
        },
      );
      if (
        response.success &&
        response.confirmed_value !== null &&
        response.confirmed_value !== undefined
      ) {
        const confirmed = response.confirmed_value;
        setParameters((current) => current.map((item) =>
          item.param_id === parameter.param_id
            ? { ...item, value: confirmed ?? item.value }
            : item
        ));
        setEdits((current) => ({
          ...current,
          [parameter.param_id]: String(confirmed),
        }));
        setNotice(response.message);
      } else {
        setError(response.message);
      }
    } catch (saveError) {
      setError(
        saveError instanceof Error
          ? saveError.message
          : "Parameter update failed.",
      );
    } finally {
      setSavingParamId(null);
      setPendingChange(null);
    }
  };

  return (
    <div
      className="params-workspace"
      style={{
        "--agent-color": agent.color,
        "--agent-color-rgb": agent.colorRgb,
      } as CSSProperties}
    >
      <UavSelector value={slot} onChange={changeSlot} disabled={busy} />

      <section className="operations-command-bar">
        <div>
          <strong>{agent.shortLabel}</strong>
          <span>{agent.type} PARAMETER CHANNEL</span>
        </div>
        <div className="operations-command-actions">
          <button
            type="button"
            className="operations-button is-primary"
            onClick={handleFetchAll}
            disabled={busy}
          >
            {busy && progress.status === "fetching"
              ? "FETCHING PARAMETERS"
              : "FETCH ALL PARAMETERS"}
          </button>
          <button
            type="button"
            className="operations-button is-secondary"
            onClick={handleRetryMissing}
            disabled={busy || !progress.missing_indices.length}
          >
            RETRY MISSING
          </button>
        </div>
      </section>

      <section className="operations-progress" aria-live="polite">
        <div>
          <strong>
            {progress.message
              || (isLoading
                ? "Loading parameter cache"
                : "Parameter channel ready")}
          </strong>
          <span>
            {progress.received} / {progress.total} PARAMETERS
          </span>
        </div>
        <div className="operations-progress-meter" aria-hidden="true">
          <span style={{ width: `${progressPercent}%` }} />
        </div>
      </section>

      {progress.status === "incomplete" && (
        <div className="params-missing-warning">
          <strong>{progress.missing_indices.length} PARAMETERS MISSING</strong>
          <span>
            Missing indices are requested one by one when you select
            RETRY MISSING.
          </span>
        </div>
      )}

      {(error || notice) && (
        <div
          className={`operations-message ${error ? "is-error" : "is-ok"}`}
          role={error ? "alert" : "status"}
        >
          {error || notice}
        </div>
      )}

      <section className="operations-section params-table-section">
        <header className="params-toolbar">
          <label className="operations-field params-search-field">
            <span>SEARCH PARAMETER ID</span>
            <input
              type="search"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="Example: ARMING_CHECK"
              autoComplete="off"
            />
          </label>
          <div className="params-table-count">
            <strong>{filteredParameters.length}</strong>
            <span>VISIBLE OF {parameters.length}</span>
          </div>
        </header>

        {isLoading && !parameters.length ? (
          <div className="operations-loading-state" aria-live="polite">
            <span />
            <span />
            <span />
            <strong>LOADING PARAMETER CACHE</strong>
          </div>
        ) : visibleParameters.length ? (
          <div className="operations-table-scroll params-table-scroll">
            <table
              className="operations-table params-table"
              aria-label={`Parameters for ${agent.shortLabel}`}
            >
              <thead>
                <tr>
                  <th>INDEX</th>
                  <th>PARAMETER ID</th>
                  <th>TYPE</th>
                  <th>VALUE</th>
                  <th>ACTION</th>
                </tr>
              </thead>
              <tbody>
                {visibleParameters.map((parameter) => {
                  const draftValue = edits[parameter.param_id]
                    ?? String(parameter.value);
                  const changed = Number(draftValue) !== parameter.value;
                  return (
                    <tr key={parameter.param_id}>
                      <td>
                        {parameter.index} / {parameter.count}
                      </td>
                      <td className="operations-table-primary">
                        {parameter.param_id}
                      </td>
                      <td>
                        {parameter.type_name}
                        <small>{parameter.type}</small>
                      </td>
                      <td>
                        <input
                          className={changed ? "is-changed" : ""}
                          type="number"
                          step="any"
                          value={draftValue}
                          onChange={(event) => setEdits((current) => ({
                            ...current,
                            [parameter.param_id]: event.target.value,
                          }))}
                          aria-label={`Value for ${parameter.param_id}`}
                        />
                      </td>
                      <td>
                        <button
                          type="button"
                          className="params-save-button"
                          onClick={() => requestSave(parameter)}
                          disabled={
                            !changed || savingParamId === parameter.param_id
                          }
                        >
                          {savingParamId === parameter.param_id
                            ? "SAVING"
                            : "SAVE"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="operations-empty-state">
            <strong>NO PARAMETERS FOUND</strong>
            <span>
              Fetch parameters from the UAV or change the search filter.
            </span>
          </div>
        )}

        <footer className="params-pagination">
          <span>
            PAGE {Math.min(page + 1, totalPages)} / {totalPages}
          </span>
          <div>
            <button
              type="button"
              onClick={() => setPage((current) => Math.max(0, current - 1))}
              disabled={page === 0}
            >
              PREVIOUS
            </button>
            <button
              type="button"
              onClick={() => setPage((current) =>
                Math.min(totalPages - 1, current + 1)
              )}
              disabled={page >= totalPages - 1}
            >
              NEXT
            </button>
          </div>
        </footer>
      </section>

      {pendingChange && (
        <div className="operations-dialog-backdrop">
          <div
            className="operations-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="param-confirm-title"
          >
            <span className="operations-dialog-warning">SAFETY CHECK</span>
            <h2 id="param-confirm-title">CONFIRM PARAMETER WRITE</h2>
            <p>
              Changing autopilot parameters can affect flight safety. Verify
              the target and value before sending.
            </p>
            <dl>
              <div>
                <dt>UAV</dt>
                <dd>{agent.shortLabel}</dd>
              </div>
              <div>
                <dt>PARAMETER</dt>
                <dd>{pendingChange.parameter.param_id}</dd>
              </div>
              <div>
                <dt>OLD VALUE</dt>
                <dd>{pendingChange.parameter.value}</dd>
              </div>
              <div>
                <dt>NEW VALUE</dt>
                <dd>{pendingChange.nextValue}</dd>
              </div>
            </dl>
            <div className="operations-dialog-actions">
              <button
                type="button"
                className="operations-button is-secondary"
                onClick={() => setPendingChange(null)}
                disabled={Boolean(savingParamId)}
              >
                CANCEL
              </button>
              <button
                type="button"
                className="operations-button is-danger"
                onClick={confirmSave}
                disabled={Boolean(savingParamId)}
              >
                {savingParamId ? "WRITING PARAMETER" : "CONFIRM WRITE"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
