import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  mockSendConversationMessage,
  mockConfirmConversation,
} from '../src/api/plans.ts';

describe('GAP-AI Interactive Conversation Flow Verification', () => {
  it('1. Missing start time triggers clarification question', () => {
    const res = mockSendConversationMessage('I want to study tomorrow evening.');
    assert.equal(res.state, 'awaiting_clarification');
    assert.equal(res.clarification_question, 'What time would you like to start?');
    assert.ok(res.conversation_id);
    assert.equal(res.needs_confirmation, false);
    assert.equal(res.created_plan, null);
    assert.ok(res.pending_plan);
    assert.equal(res.pending_plan?.title, 'Study Session');
  });

  it('2. Ambiguous bare hour triggers AM/PM clarification', () => {
    const initial = mockSendConversationMessage('I want to study tomorrow evening.');
    const convId = initial.conversation_id;

    const res = mockSendConversationMessage('At five', convId);
    assert.equal(res.state, 'awaiting_clarification');
    assert.equal(res.clarification_question, 'Do you mean 5 AM or 5 PM?');
    assert.equal(res.conversation_id, convId);
    assert.equal(res.created_plan, null);
  });

  it('3. Resolving 5 PM sets time to 17:00 and moves to awaiting_confirmation with natural summary', () => {
    const initial = mockSendConversationMessage('I want to study tomorrow evening.');
    const convId = initial.conversation_id;
    mockSendConversationMessage('At five', convId);

    const res = mockSendConversationMessage('5 PM', convId);
    assert.equal(res.state, 'awaiting_confirmation');
    assert.equal(res.needs_confirmation, true);
    assert.equal(res.pending_plan?.time, '17:00');
    assert.ok(res.confirmation_summary?.includes('5:00 PM'));
    assert.ok(res.confirmation_summary?.toLowerCase().includes('study'));
    assert.equal(res.created_plan, null, 'No plan should be saved before explicit confirmation');
  });

  it('4. Correction: "No, I meant 5 AM" updates time to 05:00 without restarting', () => {
    const initial = mockSendConversationMessage('I want to study tomorrow evening.');
    const convId = initial.conversation_id;
    mockSendConversationMessage('At five', convId);
    mockSendConversationMessage('5 PM', convId);

    const res = mockSendConversationMessage('No, I meant 5 AM', convId);
    assert.equal(res.state, 'awaiting_confirmation');
    assert.equal(res.pending_plan?.time, '05:00');
    assert.ok(res.confirmation_summary?.includes('5:00 AM'));
    assert.equal(res.created_plan, null);
  });

  it('5. Correction: "Change the time to 8 PM" updates time to 20:00', () => {
    const initial = mockSendConversationMessage('I want to study tomorrow evening.');
    const convId = initial.conversation_id;
    mockSendConversationMessage('At five', convId);
    mockSendConversationMessage('5 PM', convId);

    const res = mockSendConversationMessage('Change the time to 8 PM', convId);
    assert.equal(res.state, 'awaiting_confirmation');
    assert.equal(res.pending_plan?.time, '20:00');
    assert.ok(res.confirmation_summary?.includes('8:00 PM'));
  });

  it('6. Correction: "Make it two hours" updates duration to 120 minutes', () => {
    const initial = mockSendConversationMessage('I want to study tomorrow evening.');
    const convId = initial.conversation_id;
    mockSendConversationMessage('At five', convId);
    mockSendConversationMessage('5 PM', convId);

    const res = mockSendConversationMessage('Make it two hours', convId);
    assert.equal(res.state, 'awaiting_confirmation');
    assert.equal(res.pending_plan?.duration_minutes, 120);
    assert.ok(res.confirmation_summary?.includes('two hours'));
  });

  it('7. Correction: "Not tomorrow, Friday" updates date to Friday', () => {
    const initial = mockSendConversationMessage('I want to study tomorrow evening.');
    const convId = initial.conversation_id;
    mockSendConversationMessage('At five', convId);
    mockSendConversationMessage('5 PM', convId);

    const res = mockSendConversationMessage('Not tomorrow, Friday', convId);
    assert.equal(res.state, 'awaiting_confirmation');
    assert.ok(res.confirmation_summary?.toLowerCase().includes('friday'));
  });

  it('8. Confirmation creates exactly one plan and returns completed state', () => {
    const initial = mockSendConversationMessage('I want to study tomorrow evening.');
    const convId = initial.conversation_id;
    mockSendConversationMessage('At five', convId);
    mockSendConversationMessage('5 PM', convId);

    const confirmRes = mockConfirmConversation(convId);
    assert.equal(confirmRes.state, 'completed');
    assert.ok(confirmRes.created_plan);
    assert.equal(confirmRes.needs_confirmation, false);

    // Repeated confirmation returns existing plan idempotently
    const repeatRes = mockConfirmConversation(convId);
    assert.equal(repeatRes.state, 'completed');
    assert.equal(repeatRes.created_plan?.id, confirmRes.created_plan.id);
  });

  it('9. Cancellation clears pending creation and saves no plan', () => {
    const initial = mockSendConversationMessage('I want to study tomorrow evening.');
    const convId = initial.conversation_id;
    mockSendConversationMessage('At five', convId);

    const cancelRes = mockSendConversationMessage('Cancel that', convId);
    assert.equal(cancelRes.state, 'cancelled');
    assert.equal(cancelRes.pending_plan, null);
    assert.equal(cancelRes.created_plan, null);
    assert.ok(cancelRes.reply_text.includes('cancelled'));
  });

  it('10. English-only assistant responses across conversation turns', () => {
    const res1 = mockSendConversationMessage('I want to study tomorrow evening.');
    const turkishChars = /[çğışöüÇĞİŞÖÜ]/;
    assert.equal(turkishChars.test(res1.reply_text), false);

    const res2 = mockSendConversationMessage('At five', res1.conversation_id);
    assert.equal(turkishChars.test(res2.reply_text), false);

    const res3 = mockSendConversationMessage('5 PM', res1.conversation_id);
    assert.equal(turkishChars.test(res3.reply_text), false);

    const res4 = mockConfirmConversation(res1.conversation_id);
    assert.equal(turkishChars.test(res4.reply_text), false);
  });
});
