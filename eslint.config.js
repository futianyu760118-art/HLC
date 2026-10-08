// eslint.config.js
import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import globals from 'globals';
import pluginReact from 'eslint-plugin-react';
import pluginReactHooks from 'eslint-plugin-react-hooks';
import pluginReactRefresh from 'eslint-plugin-react-refresh';

export default [
  {
    ignores: [
      'dist/**',
      'dist-prod/**',
      'node_modules/**',
      'artifacts/**',
      'backend-python/**',
      'hengpintong-promo-video/**',
      'hrm-training-videos/**',
      'outputs/**',
      'certs/**',
      '.hypothesis/**',
      '.pytest_cache/**',
    ],
  },

  js.configs.recommended,          
  ...tseslint.configs.recommended,     
  pluginReact.configs.flat.recommended,

  {
    files: ['**/*.{js,mjs,cjs,ts,jsx,tsx}'],
    plugins: {
      'react-hooks': pluginReactHooks,
      'react-refresh': pluginReactRefresh,
    },
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
        ecmaFeatures: { jsx: true },
      },
      globals: {
        ...globals.browser,
      },
    },
    settings: {
      react: {
        version: 'detect',
      },
    },
    rules: {
      // 推荐规则
      ...pluginReactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': 'off',
      'react/jsx-uses-react': 'off',
      'react/react-in-jsx-scope': 'off',
      'react/prop-types': 'off',

      // Existing codebase still contains legacy generated files and ts-nocheck islands.
      // Keep lint useful for release risk signals without making historic formatting debt
      // block every build.
      semi: 'off',
      quotes: 'off',
      indent: 'off',
      'no-empty': ['warn', { allowEmptyCatch: true }],
      'prefer-const': 'warn',
      '@typescript-eslint/ban-ts-comment': 'off',
      '@typescript-eslint/no-explicit-any': 'off',

      // TypeScript 特有规则
      '@typescript-eslint/no-unused-vars': [
        'warn',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
    },
  },

  {
    files: ['*.{js,mjs,cjs}', 'scripts/**/*.{js,mjs,cjs}', 'vite.config.ts', 'tailwind.config.js', 'postcss.config.js'],
    languageOptions: {
      globals: {
        ...globals.node,
      },
    },
    rules: {
      'react-refresh/only-export-components': 'off',
    },
  },
];
