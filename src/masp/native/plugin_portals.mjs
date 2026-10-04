/** Keep plugin body portals in their own overlay and lifecycle. */
import React from 'react';
import * as native from 'micro-multi:react-dom-native';
export const PortalHost=React.createContext(null);
function Portal({children,target,portalKey}){
 const host=React.useContext(PortalHost);
 return native.createPortal(children,target===document.body&&host?host:target,portalKey);
}
export function createPortal(children,target,key){return React.createElement(Portal,{children,target,portalKey:key,key});}
export const {flushSync,preconnect,prefetchDNS,preinit,preinitModule,preload,preloadModule,requestFormReset,useFormState,useFormStatus,version}=native;
export default {...native,createPortal};
