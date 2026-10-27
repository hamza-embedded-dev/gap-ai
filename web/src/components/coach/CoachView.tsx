import type { RecommendationCard } from '../../api/insights.ts';
import { effectiveDuration, visibleCards } from './coachActions.ts';
import type { CoachState } from './coachActions.ts';

export interface CoachViewHandlers {
  onRefresh: () => void;
  onShowAnother: () => void;
  onRate: (card: RecommendationCard, rating: 'useful' | 'not_useful') => void;
  onDismiss: (card: RecommendationCard) => void;
  onToggleWhy: (card: RecommendationCard) => void;
  onDurationInput: (card: RecommendationCard, minutes: number) => void;
  onSaveDuration: (card: RecommendationCard) => void;
  onAddToPlans: (card: RecommendationCard) => void;
  onRequireAuth: () => void;
}

interface CoachViewProps {
  state: CoachState;
  handlers: CoachViewHandlers;
}

const SOURCE_LABELS: Record<RecommendationCard['source'], string> = {
  behavior: 'Based on your history',
  contextual: 'Based on your context',
  discovery: 'Starter idea',
};

function CoachCard({ card, state, handlers }: { card: RecommendationCard; state: CoachState; handlers: CoachViewHandlers }) {
  const busy = state.busyId !== null;
  const rating = state.ratings[card.id];
  const whyOpen = Boolean(state.whyOpen[card.id]);
  const titleId = `coach-card-${card.id}-title`;
  const whyId = `coach-card-${card.id}-why`;
  const evidenceEntries = Object.entries(card.evidence ?? {});
  const showEvidence = card.source === 'behavior' || card.source === 'contextual';

  return (
    <article className="coach-card" aria-labelledby={titleId} data-source={card.source}>
      <div className="coach-card-tags">
        <span className="coach-tag">{SOURCE_LABELS[card.source]}</span>
        {card.label && <span className="coach-tag coach-tag-muted">{card.label}</span>}
      </div>
      <h3 id={titleId} className="coach-card-title">{card.title}</h3>
      <p className="coach-card-message">{card.message}</p>

      {showEvidence && (
        <dl className="coach-evidence">
          <div>
            <dt>Evidence</dt>
            <dd>{evidenceEntries.map(([key, value]) => `${key}: ${value}`).join(' · ') || 'None'}</dd>
          </div>
          <div>
            <dt>Confidence</dt>
            <dd>{card.confidence}</dd>
          </div>
        </dl>
      )}

      <p className="coach-next-step"><strong>Next step:</strong> {card.next_step}</p>

      {whyOpen && (
        <p id={whyId} className="coach-why" role="note">
          {card.why}
          {card.source === 'discovery' ? ' This is a neutral starter and uses no history.' : ''}
        </p>
      )}

      {card.source === 'discovery' && (
        <div className="coach-duration">
          <label htmlFor={`coach-duration-${card.id}`}>Duration (minutes)</label>
          <input
            id={`coach-duration-${card.id}`}
            type="number"
            inputMode="numeric"
            min={5}
            max={1440}
            value={effectiveDuration(card, state.durations)}
            disabled={busy}
            onChange={(e) => handlers.onDurationInput(card, Number(e.target.value))}
          />
        </div>
      )}

      <div className="coach-actions" role="group" aria-label={`Actions for ${card.title}`}>
        <button
          type="button"
          className="coach-btn coach-btn-secondary"
          aria-expanded={whyOpen}
          aria-controls={whyId}
          disabled={busy}
          onClick={() => handlers.onToggleWhy(card)}
        >
          Tell me why this was suggested
        </button>
        <button
          type="button"
          className="coach-btn coach-btn-secondary"
          aria-pressed={rating === 'useful'}
          disabled={busy}
          onClick={() => handlers.onRate(card, 'useful')}
        >
          {rating === 'useful' ? 'Useful \u2713' : 'Useful'}
        </button>
        <button
          type="button"
          className="coach-btn coach-btn-secondary"
          aria-pressed={rating === 'not_useful'}
          disabled={busy}
          onClick={() => handlers.onRate(card, 'not_useful')}
        >
          {rating === 'not_useful' ? 'Not useful \u2713' : 'Not useful'}
        </button>
        <button type="button" className="coach-btn coach-btn-ghost" disabled={busy} onClick={() => handlers.onDismiss(card)}>
          Not interested
        </button>
        {card.source === 'discovery' && (
          <>
            <button type="button" className="coach-btn coach-btn-secondary" disabled={busy} onClick={() => handlers.onSaveDuration(card)}>
              Change duration
            </button>
            <button type="button" className="coach-btn coach-btn-primary" disabled={busy} onClick={() => handlers.onAddToPlans(card)}>
              {state.busyId === card.id ? 'Working\u2026' : 'Add to My Plans'}
            </button>
          </>
        )}
      </div>
    </article>
  );
}

export function CoachView({ state, handlers }: CoachViewProps) {
  const cards = visibleCards(state.cards);
  const requiresAuth = state.error?.statusCode === 401 || state.error?.errorType === 'auth_required';

  return (
    <div className="coach-page" id="personal-ai-coach">
      <header className="coach-header">
        <div>
          <h2 className="coach-title">Personal AI Coach</h2>
          <p className="coach-subtitle">
            Evidence-based ideas drawn from your plan history and stated context. Rate them to shape what you see next.
          </p>
        </div>
        <button
          type="button"
          className="coach-btn coach-btn-secondary"
          onClick={handlers.onRefresh}
          disabled={state.status === 'loading' || state.busyId !== null}
        >
          Refresh ideas
        </button>
      </header>

      <div className="coach-live" aria-live="polite">
        {state.notice && <p role="status" className="coach-banner coach-banner-success">{state.notice}</p>}
      </div>
      {state.actionError && <p role="alert" className="coach-banner coach-banner-error">{state.actionError}</p>}

      {state.status === 'loading' && (
        <div className="coach-grid" aria-busy="true" aria-label="Loading your ideas">
          {[0, 1, 2].map((i) => <div key={i} className="coach-card coach-skeleton" aria-hidden="true" />)}
          <p className="coach-sr-only" role="status">Loading your ideas…</p>
        </div>
      )}

      {state.status === 'error' && state.error && (
        <section className="coach-state coach-state-error" role="alert">
          <h3>{requiresAuth ? 'Session required' : 'Ideas could not be loaded'}</h3>
          <p>{state.error.message}</p>
          <div className="coach-actions">
            {requiresAuth ? (
              <button type="button" className="coach-btn coach-btn-primary" onClick={handlers.onRequireAuth}>Go to Demo &amp; Auth</button>
            ) : (
              <button type="button" className="coach-btn coach-btn-primary" onClick={handlers.onRefresh}>Retry</button>
            )}
          </div>
        </section>
      )}

      {state.status === 'ready' && cards.length === 0 && (
        <section className="coach-state">
          <h3>No ideas right now</h3>
          <p>No ideas are available right now. Refresh to try again.</p>
        </section>
      )}

      {state.status === 'ready' && cards.length > 0 && (
        <>
          <div className="coach-grid">
            {cards.map((card) => <CoachCard key={card.id} card={card} state={state} handlers={handlers} />)}
          </div>
          <div>
            <button type="button" className="coach-btn coach-btn-secondary" onClick={handlers.onShowAnother} disabled={state.busyId !== null}>
              Show another idea
            </button>
          </div>
        </>
      )}
    </div>
  );
}
