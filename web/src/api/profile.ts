import { apiFetch } from './client';
import type { PersonalizationProfile } from '../types/profile';
export const getProfile = () => apiFetch<PersonalizationProfile>('/me/profile');
export const updateProfile = (changes: Partial<PersonalizationProfile>) => apiFetch<PersonalizationProfile>('/me/profile', { method: 'PATCH', body: JSON.stringify(changes) });
export const deleteProfileField = (field: string) => apiFetch(`/me/profile/fields/${encodeURIComponent(field)}`, { method: 'DELETE' });
export const resetProfile = () => apiFetch('/me/profile', { method: 'DELETE' });
