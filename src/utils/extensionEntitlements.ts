import type { ExtensionCatalog, ExtensionMaturity } from './api';

const maturityLabels: Record<ExtensionMaturity, string> = {
  workflow: '业务流程',
  insight: '只读洞察',
  mock: '模拟适配',
  planned: '规划中',
};

export function extensionMaturityLabel(maturity: ExtensionMaturity): string {
  return maturityLabels[maturity];
}

export function enabledExtensionFeatures<T extends { key: string }>(
  catalog: ExtensionCatalog,
  packageKey: string,
  features: readonly T[],
): T[] {
  const extensionPackage = catalog.packages.find((item) => item.key === packageKey);
  if (!extensionPackage) return [];

  const enabledKeys = new Set(
    extensionPackage.features
      .filter((feature) => feature.enabled === true && feature.supported === true)
      .map((feature) => feature.key),
  );

  return features.filter((feature) => enabledKeys.has(`extension.${packageKey}.${feature.key}`));
}
