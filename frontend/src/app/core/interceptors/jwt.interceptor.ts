import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';
import { AuthService } from '../auth/auth.service';

const PUBLIC_ENDPOINTS = ['/identity/login', '/identity/setup'];

export const jwtInterceptor: HttpInterceptorFn = (req, next) => {
  const authService = inject(AuthService);
  const token = authService.token;

  if (token) {
    req = req.clone({
      setHeaders: {
        Authorization: `Bearer ${token}`
      }
    });
  }

  return next(req).pipe(
    catchError((err) => {
      const isPublic = PUBLIC_ENDPOINTS.some((p) => req.url.includes(p));
      // Token expirado/inválido: encerra a sessão e volta ao login
      if (err?.status === 401 && token && !isPublic) {
        authService.logout();
      }
      return throwError(() => err);
    })
  );
};
