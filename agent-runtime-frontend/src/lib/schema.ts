/** Helpers for reading the JSON Schemas that describe tool arguments. */

import type { JsonSchemaProperty } from '../api/types';

/** A readable type for a schema property, e.g. `integer | null` or `"auto" | "low"`. */
export function describeType(property: JsonSchemaProperty): string {
  if (property.enum) return property.enum.map((value) => JSON.stringify(value)).join(' | ');
  if (property.anyOf) return property.anyOf.map(describeType).join(' | ');
  return property.type ?? 'any';
}
