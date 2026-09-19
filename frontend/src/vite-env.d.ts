/// <reference types="vite/client" />

// Vite's client types declare module shapes for asset imports (the PNG logos
// in src/assets, inlined as data: URIs by the library build). Without this
// file `import logo from '@/assets/lse-logo-dark.png'` is a type error.
