import { useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Ban,
  BookOpen,
  Check,
  CircleHelp,
  ClipboardList,
  MessageCircleQuestion,
  Pencil,
  Send,
} from 'lucide-react';
import {
  cancelConversation,
  confirmConversation,
  createPlan,
  parseNaturalLanguagePlan,
  sendConversationMessage,
  validatePlanForCreation,
} from '../api/plans';
import type { ParsedPlan, Plan, PlanCategory } from '../types/plan';
import { generateIdempotencyKey } from '../utils/idempotency';
import './CreatePlan.css';

interface CreatePlanProps {
  token: string | null;
  onRequireToken?: () => void;
  onNavigatePlans?: () => void;
}

export function CreatePlan({ token, onRequireToken, onNavigatePlans }: CreatePlanProps) {
  // Input and flow states
  const [inputText, setInputText] = useState<string>('');
  const [clarifyReply, setClarifyReply] = useState<string>('');
  const [correctionText, setCorrectionText] = useState<string>('');
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [confirmationSummary, setConfirmationSummary] = useState<string | null>(null);
  const [conversationTurns, setConversationTurns] = useState<
    Array<{ sender: 'user' | 'assistant'; text: string }>
  >([]);

  const [parsedPlan, setParsedPlan] = useState<ParsedPlan | null>(null);
  const [savedPlan, setSavedPlan] = useState<Plan | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState<string | null>(null);

  // Loading & status states
  const [isParsing, setIsParsing] = useState<boolean>(false);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Controlled mock mode (default: false / Live API)
  const [mockMode, setMockMode] = useState<boolean>(false);

  // Inline edit state for confirmation
  const [isEditing, setIsEditing] = useState<boolean>(false);

  // Quick sample templates
  const SAMPLE_PROMPTS = [
    { label: 'Run tomorrow at 6 PM', text: 'I will go for a one-hour run in the park tomorrow at 18:00.', icon: Activity },
    { label: 'Code this Friday', text: 'I will work on the GAP-AI project this Friday from 2:30 PM to 4:30 PM.', icon: BookOpen },
    { label: 'Needs clarification', text: 'I want to study tomorrow evening.', icon: CircleHelp },
    { label: 'Unsupported request', text: 'Hello, can you tell me a joke today?', icon: Ban },
  ];

  const handleSelectSample = (text: string) => {
    setInputText(text);
    setErrorMessage(null);
  };

  /**
   * Submit: Send input text to the interactive conversation endpoint.
   */
  const handleParse = async (textToParse?: string) => {
    if (isParsing || isSaving) return;

    const text = (textToParse ?? inputText).trim();
    if (!text) {
      setErrorMessage('Enter a description of the plan you want to create.');
      return;
    }

    if (!token && !mockMode) {
      setErrorMessage('Sign in through Demo & Auth before making API requests.');
      if (onRequireToken) onRequireToken();
      return;
    }

    setIsParsing(true);
    setErrorMessage(null);
    setSavedPlan(null);

    try {
      const updatedTurns = [...conversationTurns, { sender: 'user' as const, text }];
      setConversationTurns(updatedTurns);

      const convResponse = await sendConversationMessage(text, conversationId, {
        language: 'en',
        mockMode,
      });

      setConversationId(convResponse.conversation_id);

      if (convResponse.state === 'awaiting_clarification') {
        const q = convResponse.clarification_question || convResponse.reply_text;
        setConversationTurns([...updatedTurns, { sender: 'assistant' as const, text: q }]);
        setParsedPlan({
          intent: 'clarify',
          title: convResponse.pending_plan?.title || 'Planned Activity',
          category: convResponse.pending_plan?.category || 'other',
          date: convResponse.pending_plan?.date || null,
          time: convResponse.pending_plan?.time || null,
          duration_minutes: convResponse.pending_plan?.duration_minutes ?? null,
          recurrence: convResponse.pending_plan?.recurrence || null,
          language: 'en',
          needs_weather_check: convResponse.pending_plan?.needs_weather_check ?? false,
          clarification_question: q,
          confidence: 0.85,
        });
        setIsEditing(false);
        setIdempotencyKey(null);
      } else if (convResponse.state === 'awaiting_confirmation') {
        const summary = convResponse.confirmation_summary || convResponse.reply_text;
        setConfirmationSummary(summary);
        setConversationTurns([...updatedTurns, { sender: 'assistant' as const, text: summary }]);
        setParsedPlan({
          intent: 'create_plan',
          title: convResponse.pending_plan?.title || 'Planned Activity',
          category: convResponse.pending_plan?.category || 'other',
          date: convResponse.pending_plan?.date || null,
          time: convResponse.pending_plan?.time || null,
          duration_minutes: convResponse.pending_plan?.duration_minutes ?? 60,
          recurrence: convResponse.pending_plan?.recurrence || null,
          language: 'en',
          needs_weather_check: convResponse.pending_plan?.needs_weather_check ?? false,
          clarification_question: null,
          confidence: 0.95,
        });
        setIsEditing(false);
        setIdempotencyKey(generateIdempotencyKey());
      } else if (convResponse.state === 'completed' && convResponse.created_plan) {
        setSavedPlan(convResponse.created_plan);
        setParsedPlan(null);
        setConfirmationSummary(null);
        setConversationTurns([...updatedTurns, { sender: 'assistant' as const, text: convResponse.reply_text }]);
      } else if (convResponse.state === 'cancelled') {
        setParsedPlan(null);
        setIsEditing(false);
        setIdempotencyKey(null);
        setConfirmationSummary(null);
        setErrorMessage('Plan creation was cancelled. No plan was saved.');
        setConversationTurns([...updatedTurns, { sender: 'assistant' as const, text: convResponse.reply_text }]);
      } else if (convResponse.state === 'unsupported') {
        setParsedPlan({
          intent: 'unsupported',
          title: null,
          category: null,
          date: null,
          time: null,
          duration_minutes: null,
          recurrence: null,
          language: 'en',
          needs_weather_check: false,
          clarification_question: null,
          confidence: 0.98,
        });
        setIsEditing(false);
        setIdempotencyKey(null);
        setConfirmationSummary(null);
        setConversationTurns([...updatedTurns, { sender: 'assistant' as const, text: convResponse.reply_text }]);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'An error occurred while processing your request.';
      setErrorMessage(msg);
      // Fallback to direct parse if conversation endpoint is unavailable
      try {
        const fallbackResult = await parseNaturalLanguagePlan(text, { language: 'en', mockMode });
        setParsedPlan(fallbackResult);
        if (fallbackResult.intent === 'create_plan') {
          setIdempotencyKey(generateIdempotencyKey());
        }
      } catch {
        // preserve original error message
      }
    } finally {
      setIsParsing(false);
    }
  };

  /**
   * Clarify flow: Send user's clarification answer within the active conversation.
   */
  const handleClarifySubmit = async () => {
    if (isParsing || isSaving) return;

    const reply = clarifyReply.trim();
    if (!reply) {
      setErrorMessage('Enter an answer to the clarification question.');
      return;
    }

    setClarifyReply('');
    await handleParse(reply);
  };

  /**
   * Correction flow: Send user's correction to adjust fields in the pending plan.
   */
  const handleCorrectionSubmit = async () => {
    if (isParsing || isSaving) return;

    const correction = correctionText.trim();
    if (!correction) return;

    setCorrectionText('');
    await handleParse(correction);
  };

  /**
   * Confirm and save the plan via POST /conversation/confirm or POST /plans.
   */
  const handleSavePlan = async () => {
    if (isSaving || isParsing) return;

    if (!parsedPlan || parsedPlan.intent !== 'create_plan') {
      setErrorMessage('No valid plan is available to save.');
      return;
    }

    if (!idempotencyKey) {
      setErrorMessage('A valid idempotency key is missing for this request.');
      return;
    }

    if (!token && !mockMode) {
      setErrorMessage('Sign in before saving this plan.');
      if (onRequireToken) onRequireToken();
      return;
    }

    // Client-side validations for required schema fields
    const validationError = validatePlanForCreation(parsedPlan);
    if (validationError) {
      setErrorMessage(validationError);
      return;
    }

    setIsSaving(true);
    setErrorMessage(null);

    try {
      let planResult: Plan;
      if (conversationId && !isEditing) {
        const convRes = await confirmConversation(conversationId, {
          mockMode,
          idempotencyKey,
        });
        if (convRes.created_plan) {
          planResult = convRes.created_plan;
        } else {
          throw new Error('Failed to create plan from conversation confirmation.');
        }
      } else {
        // Idempotency key is preserved across retries of the exact same plan request:
        planResult = await createPlan(parsedPlan, idempotencyKey, { mockMode });
      }
      setSavedPlan(planResult);
      setParsedPlan(null);
      setConfirmationSummary(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'An error occurred while saving the plan.';
      setErrorMessage(msg);
      // In case of error, idempotencyKey is preserved so the user can retry idempotently
    } finally {
      setIsSaving(false);
    }
  };

  /**
   * Regenerate idempotency key whenever plan content fields are edited.
   */
  const handleFieldChange = (field: keyof ParsedPlan, value: unknown) => {
    if (!parsedPlan) return;
    setParsedPlan({
      ...parsedPlan,
      [field]: value,
    });
    // Editing plan details represents a distinct request payload:
    setIdempotencyKey(generateIdempotencyKey());
  };

  const handleResetFlow = () => {
    setInputText('');
    setClarifyReply('');
    setCorrectionText('');
    setParsedPlan(null);
    setSavedPlan(null);
    setIdempotencyKey(null);
    setErrorMessage(null);
    setIsEditing(false);
    setConversationId(null);
    setConfirmationSummary(null);
    setConversationTurns([]);
  };

  return (
    <div className="create-plan-wrapper">
      {/* API mode controls */}
      <div className="mode-toggle-bar">
        <div className="mode-toggle-left">
          <span>Mode:</span>
          <span className={`mode-badge ${mockMode ? 'mode-mock' : 'mode-live'}`} id="api-mode-badge">
            {mockMode ? 'Test / Mock Mode' : 'Live Backend API'}
          </span>
        </div>
        <button
          type="button"
          className="mode-toggle-btn"
          id="toggle-mock-mode-btn"
          onClick={() => {
            const nextMode = !mockMode;
            setMockMode(nextMode);
            setErrorMessage(null);
          }}
        >
          {mockMode ? 'Switch to Live API' : 'Switch to Mock Mode'}
        </button>
      </div>

      {/* Error message */}
      {errorMessage && (
        <div className="alert alert-error" role="alert" id="plan-error-alert">
          <AlertTriangle className="alert-icon" aria-hidden="true" />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Unsupported request notice */}
      {parsedPlan && parsedPlan.intent === 'unsupported' && (
        <div className="alert alert-error" role="alert" id="unsupported-alert">
          <Ban className="alert-icon" aria-hidden="true" />
          <span>
            <strong>Plan not recognized:</strong> Your text could not be interpreted as a goal, activity, or action plan. Unsupported requests cannot be converted into or saved as plans.
          </span>
        </div>
      )}

      {/* Conversation Thread History */}
      {conversationTurns.length > 0 && !savedPlan && (
        <div className="conversation-stream" id="conversation-stream" aria-label="Conversation history">
          {conversationTurns.map((turn, idx) => (
            <div
              key={idx}
              className={`conversation-bubble conversation-bubble-${turn.sender}`}
            >
              <span className="bubble-sender">{turn.sender === 'user' ? 'You' : 'GAP-AI Assistant'}</span>
              <span className="bubble-text">{turn.text}</span>
            </div>
          ))}
        </div>
      )}

      {/* Step 1: Plan description */}
      {!savedPlan && (
        <section className="card plan-input-card">
          <div className="card-header">
            <h2>Describe your plan</h2>
            <span className="badge">POST /conversation</span>
          </div>

          <p className="card-desc">
            Describe your goal, date, and time in natural language. GAP-AI will parse your request,
            ask any clarification questions if details are missing, and present a confirmation summary before saving.
          </p>

          <div className="samples-row">
            <span className="samples-label">Examples:</span>
            {SAMPLE_PROMPTS.map((sample, idx) => {
              const SampleIcon = sample.icon;
              return (
                <button
                  key={idx}
                  type="button"
                  className="sample-chip"
                  onClick={() => handleSelectSample(sample.text)}
                  disabled={isParsing || isSaving}
                >
                  <SampleIcon size={15} aria-hidden="true" />
                  <span>{sample.label}</span>
                </button>
              );
            })}
          </div>

          <div className="textarea-container">
            <textarea
              id="plan-input-textarea"
              className="plan-textarea"
              placeholder="Example: I want to study tomorrow evening."
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              disabled={isParsing || isSaving}
              rows={3}
            />
            <div className="textarea-footer">
              <span>{inputText.length} characters</span>
              <span>GAP-AI Conversation Orchestrator</span>
            </div>
          </div>

          <div className="action-row">
            <button
              id="submit-parse-btn"
              type="button"
              className="btn btn-primary"
              onClick={() => handleParse()}
              disabled={isParsing || isSaving || !inputText.trim()}
            >
              {isParsing ? (
                <>
                  <span className="spinner" aria-hidden="true"></span>
                  <span>Processing...</span>
                </>
              ) : (
                'Send Message'
              )}
            </button>

            {(parsedPlan || inputText || conversationTurns.length > 0) && (
              <button
                id="reset-plan-btn"
                type="button"
                className="btn btn-secondary"
                onClick={handleResetFlow}
                disabled={isParsing || isSaving}
              >
                Clear
              </button>
            )}
          </div>
        </section>
      )}

      {/* Step 2A: Clarification question and answer */}
      {parsedPlan && parsedPlan.intent === 'clarify' && (
        <section className="card clarify-card" id="clarify-card">
          <div className="clarify-header">
            <MessageCircleQuestion className="clarify-icon" aria-hidden="true" />
            <h3 className="clarify-title">More information needed</h3>
          </div>

          <p className="card-desc">
            The plan was recognized, but some required details are missing or ambiguous. Please answer this clarification question:
          </p>

          <div className="clarify-question-box" id="clarification-question-text">
            "{parsedPlan.clarification_question}"
          </div>

          <div className="textarea-container">
            <input
              type="text"
              id="clarify-reply-input"
              className="clarify-reply-input"
              placeholder="Your answer (e.g. 'At five', '5 PM', 'Tomorrow at 6 PM')"
              value={clarifyReply}
              onChange={(e) => setClarifyReply(e.target.value)}
              disabled={isParsing}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  handleClarifySubmit();
                }
              }}
            />
          </div>

          <div className="action-row">
            <button
              id="submit-clarify-btn"
              type="button"
              className="btn btn-primary"
              onClick={handleClarifySubmit}
              disabled={isParsing || !clarifyReply.trim()}
            >
              {isParsing ? (
                <>
                  <span className="spinner" aria-hidden="true"></span>
                  <span>Submitting...</span>
                </>
              ) : (
                'Submit Reply'
              )}
            </button>
          </div>
        </section>
      )}

      {/* Step 2B: Unsupported request notice */}
      {parsedPlan && parsedPlan.intent === 'unsupported' && (
        <section className="card unsupported-card" id="unsupported-card">
          <div className="unsupported-header">
            <Ban className="alert-icon" aria-hidden="true" />
            <h3 className="unsupported-title">Plan not recognized</h3>
          </div>
          <div className="unsupported-body">
            Your text could not be interpreted as a goal, activity, or action plan. Unsupported requests are not saved. Describe the action you want to plan and try again.
          </div>
          <div className="action-row">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                setInputText('');
                setParsedPlan(null);
              }}
            >
              Try Different Text
            </button>
          </div>
        </section>
      )}

      {/* Step 2C: Confirm plan and save */}
      {parsedPlan && parsedPlan.intent === 'create_plan' && (
        <section className="card confirmation-card" id="plan-confirmation-card">
          <div className="card-header">
            <h2>Review Plan</h2>
            <span className="status-pill pill-active">Awaiting Confirmation</span>
          </div>

          {/* Explicit Confirmation Summary */}
          {confirmationSummary && (
            <div className="confirmation-summary-box" id="confirmation-summary-banner">
              {confirmationSummary}
            </div>
          )}

          <p className="card-desc">
            Review the interpreted plan details. Explicit confirmation is required before any plan is saved to the database.
          </p>

          {!isEditing ? (
            <div className="parsed-fields-grid" id="parsed-fields-view">
              <div className="parsed-field-item">
                <span className="parsed-field-label">Title</span>
                <span className="parsed-field-value" id="field-title">{parsedPlan.title}</span>
              </div>

              <div className="parsed-field-item">
                <span className="parsed-field-label">Category</span>
                <span className={`category-tag category-${parsedPlan.category || 'other'}`} id="field-category">
                  {parsedPlan.category || 'Not specified'}
                </span>
              </div>

              <div className="parsed-field-item">
                <span className="parsed-field-label">Date</span>
                <span className="parsed-field-value" id="field-date">{parsedPlan.date}</span>
              </div>

              <div className="parsed-field-item">
                <span className="parsed-field-label">Time</span>
                <span className="parsed-field-value" id="field-time">{parsedPlan.time}</span>
              </div>

              <div className="parsed-field-item">
                <span className="parsed-field-label">Duration</span>
                <span className="parsed-field-value" id="field-duration">
                  {parsedPlan.duration_minutes ? `${parsedPlan.duration_minutes} min` : '60 min (default)'}
                </span>
              </div>

              <div className="parsed-field-item">
                <span className="parsed-field-label">Weather check</span>
                <span className="parsed-field-value" id="field-weather">
                  {parsedPlan.needs_weather_check ? 'On (outdoor)' : 'Off (indoor)'}
                </span>
              </div>
            </div>
          ) : (
            <div className="edit-form-grid" id="parsed-fields-edit-grid">
              <div className="parsed-field-item">
                <label className="parsed-field-label" htmlFor="edit-title">Title</label>
                <input
                  id="edit-title"
                  type="text"
                  className="edit-input"
                  value={parsedPlan.title || ''}
                  onChange={(e) => handleFieldChange('title', e.target.value)}
                />
              </div>

              <div className="parsed-field-item">
                <label className="parsed-field-label" htmlFor="edit-category">Category</label>
                <select
                  id="edit-category"
                  className="edit-input"
                  value={parsedPlan.category || 'other'}
                  onChange={(e) => handleFieldChange('category', e.target.value as PlanCategory)}
                >
                  <option value="sport">Sport</option>
                  <option value="study">Study</option>
                  <option value="work">Work</option>
                  <option value="meeting">Meeting</option>
                  <option value="health">Health</option>
                  <option value="social">Social</option>
                  <option value="personal">Personal</option>
                  <option value="other">Other</option>
                </select>
              </div>

              <div className="parsed-field-item">
                <label className="parsed-field-label" htmlFor="edit-date">Date</label>
                <input
                  id="edit-date"
                  type="date"
                  className="edit-input"
                  value={parsedPlan.date || ''}
                  onChange={(e) => handleFieldChange('date', e.target.value)}
                />
              </div>

              <div className="parsed-field-item">
                <label className="parsed-field-label" htmlFor="edit-time">Time</label>
                <input
                  id="edit-time"
                  type="time"
                  className="edit-input"
                  value={parsedPlan.time || ''}
                  onChange={(e) => handleFieldChange('time', e.target.value)}
                />
              </div>

              <div className="parsed-field-item">
                <label className="parsed-field-label" htmlFor="edit-duration">Duration (minutes)</label>
                <input
                  id="edit-duration"
                  type="number"
                  min={5}
                  max={1440}
                  className="edit-input"
                  value={parsedPlan.duration_minutes ?? 60}
                  onChange={(e) =>
                    handleFieldChange(
                      'duration_minutes',
                      e.target.value ? parseInt(e.target.value, 10) : null
                    )
                  }
                />
              </div>
            </div>
          )}

          {/* Conversational Corrections Input */}
          <div className="correction-container">
            <div className="correction-input-row">
              <input
                type="text"
                className="correction-input"
                id="correction-input"
                placeholder="Make a correction (e.g. 'Change the time to 8 PM', 'Make it two hours', 'Not tomorrow, Friday')"
                value={correctionText}
                onChange={(e) => setCorrectionText(e.target.value)}
                disabled={isParsing || isSaving}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    handleCorrectionSubmit();
                  }
                }}
              />
              <button
                type="button"
                className="btn btn-secondary"
                id="apply-correction-btn"
                onClick={handleCorrectionSubmit}
                disabled={isParsing || isSaving || !correctionText.trim()}
              >
                <Send size={14} aria-hidden="true" />
                <span>Update</span>
              </button>
            </div>
            <p className="correction-hint">
              Natural language corrections update the pending plan in-place without restarting.
            </p>
          </div>

          {/* Idempotency key details */}
          <div className="idempotency-box">
            <span>Idempotency-Key (UUID v4):</span>
            <code className="idempotency-key-code" id="active-idempotency-key">
              {idempotencyKey}
            </code>
          </div>

          <div className="action-row">
            <button
              id="confirm-save-plan-btn"
              type="button"
              className="btn btn-success"
              onClick={handleSavePlan}
              disabled={isSaving || !idempotencyKey}
            >
              {isSaving ? (
                <>
                  <span className="spinner" aria-hidden="true"></span>
                  <span>Saving...</span>
                </>
              ) : (
                'Confirm and Save Plan'
              )}
            </button>

            <button
              id="toggle-edit-mode-btn"
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsEditing(!isEditing)}
              disabled={isSaving}
            >
              {isEditing ? 'Done Editing' : 'Edit Details'}
            </button>

            <button
              id="cancel-plan-btn"
              type="button"
              className="btn btn-secondary"
              onClick={async () => {
                if (conversationId) {
                  try {
                    await cancelConversation(conversationId, { mockMode });
                  } catch {
                    // Ignore cancel cleanup errors
                  }
                }
                setParsedPlan(null);
                setIsEditing(false);
                setIdempotencyKey(null);
                setErrorMessage(null);
                setConfirmationSummary(null);
              }}
              disabled={isSaving}
            >
              Cancel
            </button>
          </div>
        </section>
      )}

      {/* Step 3: Saved plan confirmation */}
      {savedPlan && (
        <section className="card saved-success-card" id="plan-saved-card">
          <div className="success-header">
            <Check className="success-icon" aria-hidden="true" />
            <h2 className="success-title">Plan Saved Successfully</h2>
          </div>

          <p className="card-desc">
            Your plan has been saved. Reminders and weather insights will be based on this plan.
          </p>

          <div className="plan-details-table">
            <div className="plan-detail-row">
              <span className="label">Plan ID:</span>
              <span className="val" id="saved-plan-id"><code>{savedPlan.id}</code></span>
            </div>
            <div className="plan-detail-row">
              <span className="label">Title:</span>
              <span className="val" id="saved-plan-title">{savedPlan.title}</span>
            </div>
            <div className="plan-detail-row">
              <span className="label">Start time:</span>
              <span className="val" id="saved-plan-start">{new Date(savedPlan.planned_start).toLocaleString('en-US')}</span>
            </div>
            <div className="plan-detail-row">
              <span className="label">End time:</span>
              <span className="val" id="saved-plan-end">{new Date(savedPlan.planned_end).toLocaleString('en-US')}</span>
            </div>
            <div className="plan-detail-row">
              <span className="label">Source:</span>
              <span className="val" id="saved-plan-source">{savedPlan.source}</span>
            </div>
          </div>

          <div className="action-row">
            <button
              id="create-another-plan-btn"
              type="button"
              className="btn btn-primary"
              onClick={handleResetFlow}
            >
              <Pencil size={16} aria-hidden="true" /> Create Another Plan
            </button>

            {onNavigatePlans && (
              <button
                id="view-in-my-plans-btn"
                type="button"
                className="btn btn-secondary"
                onClick={() => {
                  handleResetFlow();
                  onNavigatePlans();
                }}
              >
                <ClipboardList size={16} aria-hidden="true" /> View in My Plans
              </button>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
