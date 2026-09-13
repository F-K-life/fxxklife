# 明日见 Self Echo Companion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a polished, mobile-first frontend demo of a trustworthy AI future-self companion with onboarding, animated conversation, transparent inference correction, and a user-owned memory profile.

**Architecture:** A Vite React TypeScript single-page app uses a small state machine to switch among onboarding, companion, and profile views. Feature components own presentation while pure helpers own transcript sequencing and local persistence, allowing Vitest and Testing Library to verify the complete interaction loop without a backend.

**Tech Stack:** React 19, TypeScript, Vite, Vitest, Testing Library, CSS/SVG animation, Lucide React.

**Spec:** `docs/superpowers/specs/2026-09-12-self-echo-companion-design.md`

## Global Constraints

- Phone-first UI must fit a 390×844 viewport without horizontal overflow.
- The avatar must visibly support idle/listening/thinking/speaking states and `prefers-reduced-motion`.
- The full flow is start → voice/type → live transcript → AI understanding → correct/confirm → accept one small action.
- Psychological interpretations are labeled as tentative and must never be presented as diagnoses or facts.
- Confirmed memory entries remain inspectable, editable, removable, and locally persisted.
- The demo uses no backend or external AI/voice API.

---

### Task 1: App shell and trust onboarding

**Files:**
- Create: `package.json`
- Create: `vite.config.ts`
- Create: `tsconfig.json`
- Create: `index.html`
- Create: `src/main.tsx`
- Create: `src/App.tsx`
- Create: `src/styles.css`
- Create: `src/test/setup.ts`
- Test: `src/App.test.tsx`

**Interfaces:**
- Produces: `App(): JSX.Element`; navigation states `onboarding | companion | profile`.
- Consumes: browser `localStorage` only.

- [ ] **Step 1: Write the failing onboarding test**

```tsx
render(<App />)
expect(screen.getByText('你决定，我记住什么')).toBeInTheDocument()
await user.click(screen.getByRole('button', { name: '开始对话' }))
expect(screen.getByText('此刻，我在这里')).toBeInTheDocument()
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `npm test -- --run src/App.test.tsx`
Expected: FAIL because the project and `App` do not exist.

- [ ] **Step 3: Implement the shell and onboarding**

Create a three-step trust story with exact promises: user-controlled memory, facts separated from guesses, and delete/correct at any time. Store `gaowo-onboarded=true` only after the primary CTA is clicked; include a visible demo-reset control in settings/profile rather than forcing repeat onboarding.

- [ ] **Step 4: Run the test and build**

Run: `npm test -- --run src/App.test.tsx && npm run build`
Expected: PASS and Vite produces `dist/`.

- [ ] **Step 5: Commit**

```bash
git add package.json vite.config.ts tsconfig.json index.html src
git commit -m "feat: scaffold trusted companion onboarding"
```

### Task 2: Animated companion and simulated live conversation

**Files:**
- Create: `src/features/companion/types.ts`
- Create: `src/features/companion/demoScript.ts`
- Create: `src/features/companion/useConversationDemo.ts`
- Create: `src/features/companion/CompanionAvatar.tsx`
- Create: `src/features/companion/ConversationScreen.tsx`
- Test: `src/features/companion/useConversationDemo.test.tsx`
- Modify: `src/App.tsx`
- Modify: `src/styles.css`

**Interfaces:**
- Produces: `AgentState = 'idle' | 'listening' | 'thinking' | 'speaking'`; `useConversationDemo()` returning `{ state, transcript, response, startDemo, sendText, showInsight }`.
- Consumes: `onOpenInsight(): void` and `onOpenProfile(): void` from `App`.

- [ ] **Step 1: Write the failing state-sequence test**

```tsx
const { result } = renderHook(() => useConversationDemo())
act(() => result.current.startDemo())
expect(result.current.state).toBe('listening')
act(() => vi.advanceTimersByTime(4200))
expect(result.current.state).toBe('thinking')
act(() => vi.advanceTimersByTime(1800))
expect(result.current.state).toBe('speaking')
```

- [ ] **Step 2: Run the focused test and verify failure**

Run: `npm test -- --run src/features/companion/useConversationDemo.test.tsx`
Expected: FAIL because the hook is missing.

- [ ] **Step 3: Implement the scripted state machine and UI**

Use one cinematic demo sentence, reveal it incrementally, then show a thoughtful response. Build the avatar as production-quality inline SVG with face, eyes, aura, and state-bound CSS classes; add breathing, blinking, listening pulse, thinking orbit, and speaking mouth motion. Include waveform, text input, keyboard submission, microphone toggle, state labels, and transcript region with `aria-live="polite"`.

- [ ] **Step 4: Verify state behavior**

Run: `npm test -- --run src/features/companion/useConversationDemo.test.tsx && npm run build`
Expected: PASS; no TypeScript or bundling errors.

- [ ] **Step 5: Commit**

```bash
git add src/features/companion src/App.tsx src/styles.css
git commit -m "feat: add animated companion conversation"
```

### Task 3: Transparent insight correction and owned memory

**Files:**
- Create: `src/features/memory/memoryStore.ts`
- Create: `src/features/memory/InsightSheet.tsx`
- Create: `src/features/memory/ProfileScreen.tsx`
- Test: `src/features/memory/memoryStore.test.ts`
- Modify: `src/App.tsx`
- Modify: `src/styles.css`

**Interfaces:**
- Produces: `MemoryItem { id, category, text, source, status }`; `loadMemory()`, `saveMemory(items)`, `removeMemory(id)`, `resetDemo()`.
- Consumes: `showInsight` from the conversation hook and navigation callbacks from `App`.

- [ ] **Step 1: Write failing persistence tests**

```ts
saveMemory([{ id: 'values-1', category: 'values', text: '我重视对团队的承诺', source: '今天的对话', status: 'confirmed' }])
expect(loadMemory()).toHaveLength(1)
removeMemory('values-1')
expect(loadMemory()).toEqual([])
```

- [ ] **Step 2: Run the focused test and verify failure**

Run: `npm test -- --run src/features/memory/memoryStore.test.ts`
Expected: FAIL because the store does not exist.

- [ ] **Step 3: Implement inference review and profile controls**

The insight sheet must visibly separate “你告诉我的”, “我正在猜的”, and “我想记住的”. Require an explicit confirmation before writing memory. “不太对” changes the inference to a correction state instead of storing it. The profile groups confirmed entries by value, drain, support, and practice; each entry exposes source, edit, and delete controls. Add one-click demo reset.

- [ ] **Step 4: Verify persistence and build**

Run: `npm test -- --run src/features/memory/memoryStore.test.ts && npm run build`
Expected: PASS with valid production output.

- [ ] **Step 5: Commit**

```bash
git add src/features/memory src/App.tsx src/styles.css
git commit -m "feat: add transparent memory controls"
```

### Task 4: Micro-action completion and mobile visual QA

**Files:**
- Create: `src/features/action/MicroAction.tsx`
- Modify: `src/App.tsx`
- Modify: `src/styles.css`
- Modify: `src/App.test.tsx`

**Interfaces:**
- Produces: `MicroAction({ onComplete }): JSX.Element` with accepted and completed states.
- Consumes: accepted insight confirmation from `App`.

- [ ] **Step 1: Add the failing end-to-end component test**

```tsx
await user.click(screen.getByRole('button', { name: '说得对' }))
await user.click(screen.getByRole('button', { name: '记住这一点' }))
expect(screen.getByText('给队友发一句真实的进度')).toBeInTheDocument()
await user.click(screen.getByRole('button', { name: '我做完了' }))
expect(screen.getByText('这就是向前的一小步')).toBeInTheDocument()
```

- [ ] **Step 2: Run and verify the interaction test fails**

Run: `npm test -- --run src/App.test.tsx`
Expected: FAIL because the micro-action is absent.

- [ ] **Step 3: Implement the action state and final polish**

Show one five-minute action after memory confirmation. Add focus-visible states, 44px touch targets, safe-area padding, reduced-motion fallbacks, 390×844 layout rules, and wider-screen phone framing without changing the mobile information hierarchy.

- [ ] **Step 4: Run full automated verification**

Run: `npm test -- --run && npm run build`
Expected: all tests PASS and production build succeeds.

- [ ] **Step 5: Run browser QA**

Open the Vite preview at 390×844, complete onboarding, start the demo, wait through listening/thinking/speaking, correct and confirm an insight, complete the micro-action, inspect/delete a profile item, and reset the demo. Capture the main conversation screen and compare it to the approved design and user reference for hierarchy, palette, avatar prominence, typography, spacing, icon style, and first-viewport reachability.

- [ ] **Step 6: Commit**

```bash
git add src
git commit -m "feat: complete future-self companion demo"
```
