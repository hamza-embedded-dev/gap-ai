import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const webSrcDir = path.resolve(__dirname, '../src');

describe('GAP-AI W1-4 Web Integration Bug Fixes Verification Tests', () => {
  describe('1. CreatePlan Form Handling & Double Submission Protection', () => {
    const createPlanContent = fs.readFileSync(path.join(webSrcDir, 'pages/CreatePlan.tsx'), 'utf-8');

    it('handleParse must have in-flight guard to prevent duplicate parsing requests', () => {
      assert.ok(
        createPlanContent.includes('if (isParsing || isSaving) return;'),
        'handleParse/handleClarifySubmit/handleSavePlan must check in-flight state'
      );
    });

    it('handleSavePlan must execute validatePlanForCreation before sending to API', () => {
      assert.ok(
        createPlanContent.includes('validatePlanForCreation(parsedPlan)'),
        'handleSavePlan must call validatePlanForCreation to prevent 422 errors'
      );
    });

    it('Cancel button must reset parsedPlan, isEditing, idempotencyKey and errorMessage', () => {
      assert.ok(
        createPlanContent.includes('id="cancel-plan-btn"'),
        'Cancel button must exist'
      );
      assert.ok(
        createPlanContent.includes('setIsEditing(false)'),
        'Cancel button must reset isEditing state'
      );
      assert.ok(
        createPlanContent.includes('setIdempotencyKey(null)'),
        'Cancel button must reset idempotencyKey'
      );
      assert.ok(
        createPlanContent.includes('setErrorMessage(null)'),
        'Cancel button must reset errorMessage'
      );
    });

    it('Saved plan success card must provide "View in My Plans" action linked to onNavigatePlans', () => {
      assert.ok(
        createPlanContent.includes('id="view-in-my-plans-btn"'),
        'CreatePlan must render "View in My Plans" button upon save success'
      );
      assert.ok(
        createPlanContent.includes('onNavigatePlans();'),
        'Clicking View in My Plans must invoke onNavigatePlans callback'
      );
    });
  });

  describe('2. App Tab Navigation Integration', () => {
    const appContent = fs.readFileSync(path.join(webSrcDir, 'App.tsx'), 'utf-8');

    it('App.tsx must pass onNavigatePlans to CreatePlan to switch tab to plans', () => {
      assert.ok(
        appContent.includes("onNavigatePlans={() => setActiveTab('plans')}"),
        'App.tsx must wire onNavigatePlans callback to switch tab to plans'
      );
    });
  });

  describe('3. OutcomeButtons Localization & Date Safety', () => {
    const outcomeContent = fs.readFileSync(path.join(webSrcDir, 'components/OutcomeButtons.tsx'), 'utf-8');

    it('Button submission text must be "Saving..." in English and must not contain "Kaydediliyor..."', () => {
      assert.ok(
        outcomeContent.includes('<span>Saving...</span>'),
        'OutcomeButtons must show English "Saving..." spinner text'
      );
      assert.strictEqual(
        outcomeContent.includes('Kaydediliyor'),
        false,
        'OutcomeButtons must not contain leftover Turkish string "Kaydediliyor"'
      );
    });

    it('formatOutcomeTime must be exported and handle invalid date strings without returning "Invalid Date"', () => {
      assert.ok(
        outcomeContent.includes('formatOutcomeTime'),
        'formatOutcomeTime must be imported and used in OutcomeButtons'
      );
      const plansContent = fs.readFileSync(path.join(webSrcDir, 'api/plans.ts'), 'utf-8');
      assert.ok(
        plansContent.includes('export function formatOutcomeTime'),
        'formatOutcomeTime must be defined in plans.ts'
      );
      assert.ok(
        plansContent.includes('isNaN(d.getTime())'),
        'formatOutcomeTime must validate timestamp with isNaN'
      );
    });
  });

  describe('4. API Client Pydantic Detail Normalization', () => {
    const clientContent = fs.readFileSync(path.join(webSrcDir, 'api/client.ts'), 'utf-8');

    it('client.ts must format array-based detail errors into readable string', () => {
      assert.ok(
        clientContent.includes('Array.isArray(errorJson.detail)'),
        'apiFetch must detect array-based detail payload from Pydantic'
      );
      assert.ok(
        clientContent.includes('join('),
        'apiFetch must join formatted validation messages'
      );
    });

    it('client.ts must format object-based detail errors using JSON.stringify', () => {
      assert.ok(
        clientContent.includes('JSON.stringify(errorJson.detail)'),
        'apiFetch must serialize object-based detail payload'
      );
    });
  });

  describe('5. Plans API Outcome Contract Enforcement', () => {
    const plansContent = fs.readFileSync(path.join(webSrcDir, 'api/plans.ts'), 'utf-8');

    it('reportPlanOutcome must strictly force postponed_to to null unless status is postponed', () => {
      assert.ok(
        plansContent.includes("status === 'postponed'"),
        'reportPlanOutcome must check status === "postponed" before attaching postponed_to'
      );
    });

    it('plans.ts must export validatePlanForCreation validator', () => {
      assert.ok(
        plansContent.includes('export function validatePlanForCreation'),
        'validatePlanForCreation must be exported'
      );
    });
  });
});
