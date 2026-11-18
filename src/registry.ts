// Registry definitions for KAINE keys.
// Added tier metadata to each key entry.

export type Tier = 'basic' | 'standard' | 'advanced';

export interface KeyMetadata {
  /** Human‑readable description of the key */
  description: string;
  /** Tier classification indicating feature level */
  tier: Tier;
  /** Optional deprecation notice */
  deprecated?: boolean;
}

/**
 * Central lookup of all supported keys.
 * Each key is mapped to its metadata, now including tier information.
 */
export const KEY_REGISTRY: Record<string, KeyMetadata> = {
  // Example entries – extend as needed.
  'user.create': {
    description: 'Create a new user account',
    tier: 'basic',
  },
  'user.update': {
    description: 'Update existing user information',
    tier: 'standard',
  },
  'user.delete': {
    description: 'Permanently remove a user',
    tier: 'advanced',
  },
  // Additional keys should follow the same structure.
};
