import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';
import { AuthService } from '../auth/auth.service';
import { ErrorNotifier } from '../http/error-notifier.service';

const PUBLIC_ENDPOINTS = ['/identity/login', '/identity/setup'];

export const jwtInterceptor: HttpInterceptorFn = (req, next) => {
  const authService = inject(AuthService);
  const notifier = inject(ErrorNotifier);
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
      if (err?.status === 401 && token && !isPublic) {
        // Token expirado, revogado ou inválido: guarda a página, encerra a sessão e avisa
        notifier.sessionEnded();
      } else if (err?.status === 0 || err?.status >= 500) {
        // Sem conexão ou erro do servidor: aviso global (sem repetir); cada tela mostra também o seu estado de erro
        notifier.serverProblem(err.status);
      }
      return throwError(() => err);
    })
  );
};
