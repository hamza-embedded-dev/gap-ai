import type { Plan, OutcomeStatus } from '../types/plan.ts';

export type PlanSort = 'created_newest' | 'created_oldest' | 'start_nearest' | 'start_farthest';
export type PlanStatusFilter = 'all' | 'pending' | OutcomeStatus;
export type PlanTimeFilter = 'all' | 'today' | 'tomorrow' | 'this_week' | 'past' | 'future';

export interface PlanFilters {
  status: PlanStatusFilter;
  time: PlanTimeFilter;
  category: string;
  search: string;
}

export const DEFAULT_PLAN_FILTERS: PlanFilters = {
  status: 'all',
  time: 'all',
  category: 'all',
  search: '',
};

function timestamp(value: unknown): number | null {
  if (typeof value !== 'string' || value.trim() === '') return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function stableIdCompare(left: Plan, right: Plan): number {
  return left.id.localeCompare(right.id);
}

function createdCompare(left: Plan, right: Plan, direction: 1 | -1): number {
  const leftTime = timestamp(left.created_at);
  const rightTime = timestamp(right.created_at);
  if (leftTime === null && rightTime !== null) return 1;
  if (rightTime === null && leftTime !== null) return -1;
  if (leftTime !== null && rightTime !== null && leftTime !== rightTime) {
    return direction * (leftTime - rightTime);
  }
  return stableIdCompare(left, right);
}

function planDateCompare(left: Plan, right: Plan, direction: 1 | -1): number {
  const leftTime = timestamp(left.planned_start);
  const rightTime = timestamp(right.planned_start);
  // Missing/invalid plan dates always sort after dated plans in either direction.
  if (leftTime === null && rightTime !== null) return 1;
  if (rightTime === null && leftTime !== null) return -1;
  if (leftTime !== null && rightTime !== null && leftTime !== rightTime) {
    return direction * (leftTime - rightTime);
  }
  // Date ties use the newest creation timestamp, then a stable ID order.
  return createdCompare(left, right, -1);
}

function localDayStart(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function addLocalDays(date: Date, days: number): Date {
  const result = new Date(date);
  result.setDate(result.getDate() + days);
  return result;
}

function matchesTimeFilter(planTime: number | null, filter: PlanTimeFilter, now: Date): boolean {
  if (filter === 'all') return true;
  if (planTime === null) return false;

  const today = localDayStart(now).getTime();
  const tomorrow = addLocalDays(new Date(today), 1).getTime();
  const dayAfterTomorrow = addLocalDays(new Date(tomorrow), 1).getTime();

  switch (filter) {
    case 'today':
      return planTime >= today && planTime < tomorrow;
    case 'tomorrow':
      return planTime >= tomorrow && planTime < dayAfterTomorrow;
    case 'this_week': {
      // Use the local calendar's Monday-to-Monday week boundary.
      const weekday = new Date(today).getDay();
      const daysSinceMonday = (weekday + 6) % 7;
      const weekStart = addLocalDays(new Date(today), -daysSinceMonday).getTime();
      const weekEnd = addLocalDays(new Date(weekStart), 7).getTime();
      return planTime >= weekStart && planTime < weekEnd;
    }
    case 'past':
      return planTime < now.getTime();
    case 'future':
      return planTime >= now.getTime();
    default:
      return true;
  }
}

function searchableDescription(plan: Plan): string {
  // The current Plan contract has no description field; include it only if an
  // API response already supplies one, without claiming it is a stored field.
  const optional = plan as Plan & { description?: unknown };
  return typeof optional.description === 'string' ? optional.description : '';
}

function foldSearchText(value: string): string {
  return value.toLocaleLowerCase('tr');
}

export function sortAndFilterPlans(
  plans: readonly Plan[],
  filters: PlanFilters = DEFAULT_PLAN_FILTERS,
  sort: PlanSort = 'created_newest',
  now: Date = new Date(),
): Plan[] {
  const query = foldSearchText(filters.search.trim());
  const filtered = plans.filter((plan) => {
    if (filters.category !== 'all' && plan.category !== filters.category) return false;

    if (filters.status !== 'all') {
      const status = plan.latest_outcome?.status ?? 'pending';
      if (status !== filters.status) return false;
    }

    if (!matchesTimeFilter(timestamp(plan.planned_start), filters.time, now)) return false;

    if (query) {
      const content = foldSearchText(`${plan.title} ${searchableDescription(plan)}`);
      if (!content.includes(query)) return false;
    }

    return true;
  });

  return [...filtered].sort((left, right) => {
    switch (sort) {
      case 'created_oldest':
        return createdCompare(left, right, 1);
      case 'start_nearest':
        return planDateCompare(left, right, 1);
      case 'start_farthest':
        return planDateCompare(left, right, -1);
      case 'created_newest':
      default:
        return createdCompare(left, right, -1);
    }
  });
}

export function countActivePlanFilters(filters: PlanFilters): number {
  return Number(filters.status !== 'all') + Number(filters.time !== 'all') +
    Number(filters.category !== 'all') + Number(filters.search.trim() !== '');
}

export function getPlanCategories(plans: readonly Plan[]): string[] {
  return Array.from(new Set(
    plans.map((plan) => plan.category).filter((category) => typeof category === 'string' && category.trim() !== '')
  )).sort((left, right) => left.localeCompare(right));
}
