export type ApiQueryValue = string | number | boolean | null | undefined;
export type ApiQuery = Record<string, ApiQueryValue>;
export type ApiPayload = Record<string, unknown>;

export interface PaginatedResponse<T> {
  items?: T[];
  total?: number;
  page?: number;
  size?: number;
}
