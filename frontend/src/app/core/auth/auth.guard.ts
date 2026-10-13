import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { map } from 'rxjs';
import { AuthService } from './auth.service';

/**
 * Exige sessão válida. Aguarda o carregamento do usuário (/me) antes de decidir,
 * evitando que um refresh da página avalie permissões com usuário ainda nulo.
 * Força a troca de senha quando exigida pelo backend.
 */
export const authGuard: CanActivateFn = (_route, state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (!authService.token) {
    return router.createUrlTree(['/login']);
  }

  return authService.ensureUser().pipe(
    map((user) => {
      if (!user) {
        return router.createUrlTree(['/login']);
      }
      if (user.must_change_password && !state.url.startsWith('/change-password')) {
        return router.createUrlTree(['/change-password']);
      }
      return true;
    })
  );
};

/**
 * Exige uma permissão específica (ou admin). Sem permissão, redireciona ao dashboard.
 * A autorização real continua no backend; este guard evita telas inacessíveis via URL direta.
 */
export const permissionGuard = (permission: string): CanActivateFn => {
  return () => {
    const authService = inject(AuthService);
    const router = inject(Router);

    return authService.ensureUser().pipe(
      map((user) => {
        if (!user) {
          return router.createUrlTree(['/login']);
        }
        return authService.hasPermission(permission) ? true : router.createUrlTree(['/dashboard']);
      })
    );
  };
};

/** Impede usuário já autenticado de voltar à tela de login. */
export const guestGuard: CanActivateFn = () => {
  const authService = inject(AuthService);
  const router = inject(Router);
  return authService.token ? router.createUrlTree(['/dashboard']) : true;
};
