// JSON Schema 子集运行时。契约数据由 scripts/gen_web_contracts.py 生成，本文件只解释 schema。

export interface JsonSchema {
  $ref?: string;
  type?: "object" | "array" | "string" | "integer" | "number" | "boolean" | "null";
  enum?: unknown[];
  const?: unknown;
  anyOf?: JsonSchema[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  additionalProperties?: boolean | JsonSchema;
  items?: JsonSchema;
  prefixItems?: JsonSchema[];
  minItems?: number;
  maxItems?: number;
  uniqueItems?: boolean;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  "x-trimmed-nonempty"?: boolean;
  "x-datetime"?: boolean;
  "x-finite"?: boolean;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function hasExactKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
): boolean {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return (
    actual.length === expected.length &&
    actual.every((key, index) => key === expected[index])
  );
}

export function isId(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{32}$/.test(value);
}

export function isIdArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isId) && new Set(value).size === value.length;
}

export function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

export function isPositiveInteger(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) >= 1;
}

export function isNonNegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) >= 0;
}

export function isNullableNonNegativeInteger(value: unknown): value is number | null {
  return value === null || isNonNegativeInteger(value);
}

export function isStringFields(
  value: Record<string, unknown>,
  fields: readonly string[],
): boolean {
  return fields.every((field) => typeof value[field] === "string");
}

export function isThreadId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9._:-]{1,256}$/.test(value);
}

export function isVideoSeed(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^[0-9]{1,19}$/.test(value) &&
    BigInt(value) <= 9223372036854775807n
  );
}

export function checkSchema(
  schema: JsonSchema,
  value: unknown,
  root: Record<string, JsonSchema>,
): boolean {
  if (schema.$ref) {
    const target = root[schema.$ref];
    return target !== undefined && checkSchema(target, value, root);
  }
  if (Object.prototype.hasOwnProperty.call(schema, "const")) {
    return value === schema.const;
  }
  if (schema.enum) {
    return schema.enum.some((item) => item === value);
  }
  if (schema.anyOf) {
    return schema.anyOf.some((item) => checkSchema(item, value, root));
  }
  switch (schema.type) {
    case "object":
      return checkObject(schema, value, root);
    case "array":
      return checkArray(schema, value, root);
    case "string":
      return checkString(schema, value);
    case "integer":
      return checkNumber(schema, value, true);
    case "number":
      return checkNumber(schema, value, false);
    case "boolean":
      return typeof value === "boolean";
    case "null":
      return value === null;
    default:
      return false;
  }
}

function checkObject(
  schema: JsonSchema,
  value: unknown,
  root: Record<string, JsonSchema>,
): boolean {
  if (!isRecord(value)) return false;
  const properties = schema.properties ?? {};
  for (const key of schema.required ?? []) {
    if (!(key in value)) return false;
  }
  for (const key of Object.keys(value)) {
    const property = properties[key];
    if (property) {
      if (!checkSchema(property, value[key], root)) return false;
      continue;
    }
    const extra = schema.additionalProperties;
    if (extra === false || extra === undefined) return false;
    if (extra !== true && !checkSchema(extra, value[key], root)) return false;
  }
  return true;
}

function checkArray(
  schema: JsonSchema,
  value: unknown,
  root: Record<string, JsonSchema>,
): boolean {
  if (!Array.isArray(value)) return false;
  if (schema.minItems !== undefined && value.length < schema.minItems) return false;
  if (schema.maxItems !== undefined && value.length > schema.maxItems) return false;
  if (schema.uniqueItems && !uniqueItems(value)) return false;
  if (schema.prefixItems) {
    for (const [index, itemSchema] of schema.prefixItems.entries()) {
      if (index < value.length && !checkSchema(itemSchema, value[index], root)) return false;
    }
    if (schema.items) {
      for (const item of value.slice(schema.prefixItems.length)) {
        if (!checkSchema(schema.items, item, root)) return false;
      }
    }
    return true;
  }
  if (!schema.items) return true;
  return value.every((item) => checkSchema(schema.items as JsonSchema, item, root));
}

function checkString(schema: JsonSchema, value: unknown): boolean {
  if (typeof value !== "string") return false;
  if (schema.minLength !== undefined && value.length < schema.minLength) return false;
  if (schema.maxLength !== undefined && value.length > schema.maxLength) return false;
  if (schema.pattern !== undefined && new RegExp(schema.pattern).test(value) === false) {
    return false;
  }
  if (schema["x-trimmed-nonempty"] && value.trim().length === 0) return false;
  if (schema["x-datetime"] && Number.isNaN(Date.parse(value))) return false;
  return true;
}

function checkNumber(schema: JsonSchema, value: unknown, integer: boolean): boolean {
  if (typeof value !== "number") return false;
  if (integer && !Number.isInteger(value)) return false;
  if (schema["x-finite"] && !Number.isFinite(value)) return false;
  if (schema.minimum !== undefined && !(value >= schema.minimum)) return false;
  if (schema.maximum !== undefined && !(value <= schema.maximum)) return false;
  if (schema.exclusiveMinimum !== undefined && !(value > schema.exclusiveMinimum)) return false;
  if (schema.exclusiveMaximum !== undefined && !(value < schema.exclusiveMaximum)) return false;
  return true;
}

function uniqueItems(values: unknown[]): boolean {
  const seen = new Set<string>();
  for (const value of values) {
    const key = stableKey(value);
    if (seen.has(key)) return false;
    seen.add(key);
  }
  return true;
}

function stableKey(value: unknown): string {
  if (value === null || typeof value !== "object") return `${typeof value}:${String(value)}`;
  return JSON.stringify(value);
}
