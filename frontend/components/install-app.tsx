"use client";
import {useEffect} from 'react';
export function InstallApp(){useEffect(()=>{if('serviceWorker'in navigator&&window.isSecureContext)navigator.serviceWorker.register('/narcissus-sw.js').catch(()=>{});},[]);return null;}
