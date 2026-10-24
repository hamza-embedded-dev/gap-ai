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
} from 'lucide-react';
import { createPlan, parseNaturalLanguagePlan, validatePlanForCreation } from '../api/plans';
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
    { label: 'Needs clarification', text: 'I will go for a run tomorrow.', icon: CircleHelp },
    { label: 'Unsupported request', text: 'Hello, can you tell me a joke today?', icon: Ban },
  ];

  const handleSelectSample = (text: string) => {
    setInputText(text);
    setErrorMessage(null);
  };

  /**
   * Submit: Send input text to the /parse endpoint.
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
      const result = await parseNaturalLanguagePlan(text, {
        language: 'en',
        mockMode,
      });

      setParsedPlan(result);
      setIsEditing(false);

      if (result.intent === 'create_plan') {
        // Generate a fresh UUID idempotency key for this confirmation session:
        setIdempotencyKey(generateIdempotencyKey());
      } else {
        setIdempotencyKey(null);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'An error occurred while parsing the text.';
      setErrorMessage(msg);
      setParsedPlan(null);
    } finally {
      setIsParsing(false);
    }
  };

  /**
   * Clarify flow: Combine the user's answer with the original input and re-parse.
   */
  const handleClarifySubmit = async () => {
    if (isParsing || isSaving) return;

    const reply = clarifyReply.trim();
    if (!reply) {
      setErrorMessage('Enter an answer to the clarification question.');
      return;
    }

    // Contract rule: Combine original input with clarification answer
    const combinedText = `${inputText.trim()}. ${reply}`;
    setInputText(combinedText);
    setClarifyReply('');
    await handleParse(combinedText);
  };

  /**
   * Confirm and save the plan via POST /plans.
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
      // Idempotency key is preserved across retries of the exact same plan request:
      const planResult = await createPlan(parsedPlan, idempotencyKey, { mockMode });
      setSavedPlan(planResult);
      setParsedPlan(null);
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
    setParsedPlan(null);
    setSavedPlan(null);
    setIdempotencyKey(null);
    setErrorMessage(null);
    setIsEditing(false);
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

      {/* Step 1: Plan description */}
      {!savedPlan && (
        <section className="card plan-input-card">
          <div className="card-header">
            <h2>Describe your plan</h2>
            <span className="badge">POST /parse</span>
          </div>

          <p className="card-desc">
            Describe your goal, date, and time in natural language. GAP-AI will parse your request
            and present the plan for your review.
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
              placeholder="Example: I will go for a one-hour run in the park tomorrow at 18:00."
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              disabled={isParsing || isSaving}
              rows={3}
            />
            <div className="textarea-footer">
              <span>{inputText.length} characters</span>
              <span>AI plan schema (ai/schema.json)</span>
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
                  <span>Parsing...</span>
                </>
              ) : (
                'Parse Plan'
              )}
            </button>

            {(parsedPlan || inputText) && (
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
            The plan was recognized, but some required details are missing or unclear. Please answer this clarification question:
          </p>

          <div className="clarify-question-box" id="clarification-question-text">
            "{parsedPlan.clarification_question}"
          </div>

          <div className="textarea-container">
            <input
              type="text"
              id="clarify-reply-input"
              className="clarify-reply-input"
              placeholder="Your answer (for example, 6:30 PM)"
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
                'Submit and Parse Again'
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
            <span className="status-pill pill-active">Ready</span>
          </div>

          <p className="card-desc">
            Review the parsed plan details. Your plan will be saved when you confirm.
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
              onClick={() => {
                setParsedPlan(null);
                setIsEditing(false);
                setIdempotencyKey(null);
                setErrorMessage(null);
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
