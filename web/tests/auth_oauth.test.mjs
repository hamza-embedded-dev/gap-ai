import { describe, it, before, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const webSrcDir = path.resolve(__dirname, '../src');

describe('GAP-AI Google OAuth 2.0 & Supabase Auth Unit & Integration Tests', () => {
  describe('1. Redirect URL Validation & Open-Redirect Protection', () => {
    it('validateRedirectUrl only permits approved domains and rejects arbitrary untrusted targets', async () => {
      // Mock window.location for Node test environment
      globalThis.window = {
        location: {
          origin: 'https://gap-ai-demo.netlify.app',
          href: 'https://gap-ai-demo.netlify.app',
        },
        history: {
          replaceState: () => {},
        },
      };

      const { validateRedirectUrl } = await import('../src/utils/supabase.ts');

      // Valid current origin
      assert.equal(
        validateRedirectUrl('https://gap-ai-demo.netlify.app/plans'),
        'https://gap-ai-demo.netlify.app/plans'
      );

      // Valid local development origin
      assert.equal(
        validateRedirectUrl('http://localhost:5173/'),
        'http://localhost:5173/'
      );

      // Malicious / open redirect attempt to attacker domain must be rejected and fallback to current origin
      assert.equal(
        validateRedirectUrl('https://malicious-phishing.com/steal-token'),
        'https://gap-ai-demo.netlify.app'
      );
    });
  });

  describe('2. OAuth Error & Cancellation Detection', () => {
    it('extractOAuthErrorFromUrl detects access_denied cancellation and sanitizes window history', async () => {
      let replacedUrl = '';
      globalThis.window = {
        location: {
          href: 'https://gap-ai-demo.netlify.app/?error=access_denied&error_description=User+declined',
          pathname: '/',
          search: '?error=access_denied&error_description=User+declined',
          hash: '',
        },
        history: {
          replaceState: (_state, _title, url) => {
            replacedUrl = url;
          },
        },
      };

      const { extractOAuthErrorFromUrl } = await import('../src/utils/auth.ts');
      const errorMsg = extractOAuthErrorFromUrl();

      assert.equal(errorMsg, 'Google sign-in was cancelled.');
      assert.equal(replacedUrl, '/');
    });

    it('extractOAuthErrorFromUrl detects OAuth error parameters inside URL hash', async () => {
      let replacedUrl = '';
      globalThis.window = {
        location: {
          href: 'https://gap-ai-demo.netlify.app/#error=server_error&error_description=OAuth+failed',
          pathname: '/',
          search: '',
          hash: '#error=server_error&error_description=OAuth+failed',
        },
        history: {
          replaceState: (_state, _title, url) => {
            replacedUrl = url;
          },
        },
      };

      const { extractOAuthErrorFromUrl } = await import('../src/utils/auth.ts');
      const errorMsg = extractOAuthErrorFromUrl();

      assert.equal(errorMsg, 'OAuth failed');
      assert.equal(replacedUrl, '/');
    });
  });

  describe('3. Supabase Client Configuration & Graceful Fallback', () => {
    it('isSupabaseConfigured returns boolean and does not throw when env vars are missing', async () => {
      const { isSupabaseConfigured } = await import('../src/utils/supabase.ts');
      const configured = isSupabaseConfigured();
      assert.equal(typeof configured, 'boolean');
    });

    it('signOutUser clears stored tokens and handles signOut gracefully', async () => {
      let itemRemoved = '';
      globalThis.window = {
        localStorage: {
          getItem: () => 'sample_token',
          setItem: () => {},
          removeItem: (key) => {
            itemRemoved = key;
          },
        },
      };

      const { signOutUser } = await import('../src/utils/supabase.ts');
      const result = await signOutUser();

      assert.equal(result.error, null);
      assert.equal(itemRemoved, 'gap_access_token');
    });
  });

  describe('4. Component Static Verification', () => {
    it('GoogleAuthButton.tsx renders Continue with Google with accessible button role and SVG icon', () => {
      const btnPath = path.join(webSrcDir, 'components/auth/GoogleAuthButton.tsx');
      assert.ok(fs.existsSync(btnPath), 'GoogleAuthButton.tsx must exist');
      const content = fs.readFileSync(btnPath, 'utf-8');

      assert.ok(content.includes('Continue with Google'), 'Must have Continue with Google label');
      assert.ok(content.includes('google-icon'), 'Must include Google SVG icon');
      assert.ok(content.includes('Connecting to Google...'), 'Must provide clear connecting / loading state');
      assert.ok(content.includes('id="google-auth-btn"'), 'Must have unique accessible ID');
    });

    it('PublicLanding.tsx exposes public overview and Google sign-in actions', () => {
      const landingPath = path.join(webSrcDir, 'components/auth/PublicLanding.tsx');
      assert.ok(fs.existsSync(landingPath), 'PublicLanding.tsx must exist');
      const content = fs.readFileSync(landingPath, 'utf-8');

      assert.ok(content.includes('Goal &amp; Action Planning') || content.includes('Goal & Action Planning'));
      assert.ok(content.includes('GoogleAuthButton'));
      assert.ok(content.includes('Start 24-Hour Demo') || content.includes('Try Demo'));
    });

    it('AuthRequiredCard.tsx renders clear sign-in required message for protected features', () => {
      const cardPath = path.join(webSrcDir, 'components/auth/AuthRequiredCard.tsx');
      assert.ok(fs.existsSync(cardPath), 'AuthRequiredCard.tsx must exist');
      const content = fs.readFileSync(cardPath, 'utf-8');

      assert.ok(content.includes('Sign in to Access'));
      assert.ok(content.includes('Private &amp; Isolated') || content.includes('Private & Isolated'));
      assert.ok(content.includes('GoogleAuthButton'));
    });

    it('App.tsx integrates Google OAuth, header sign-in, user-profile chip and sign-out', () => {
      const appPath = path.join(webSrcDir, 'App.tsx');
      const content = fs.readFileSync(appPath, 'utf-8');

      assert.ok(content.includes('GoogleAuthButton'), 'App.tsx must include GoogleAuthButton');
      assert.ok(content.includes('header-sign-out-btn'), 'App.tsx must include header sign-out button');
      assert.ok(content.includes('user-profile-chip'), 'App.tsx must include user profile badge');
      assert.ok(content.includes('Google OAuth 2.0'), 'Demo & Auth tab must include Google OAuth section');
      assert.ok(content.includes('onSupabaseAuthStateChange'), 'App.tsx must listen to auth state changes');
    });
  });
});
