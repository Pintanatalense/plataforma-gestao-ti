import { Component, OnInit, inject, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { apiErrorMessage } from '../../../core/http/api-error';
import { LoadStateComponent } from '../../../shared/components/load-state/load-state.component';
import { IdentityService, User } from '../../../core/services/identity.service';
import { generateTemporaryPassword } from '../../../core/auth/temporary-password';
import { UserDialogComponent } from './user-dialog.component';
import { UserAccessDialogComponent } from './user-access-dialog.component';

@Component({
  selector: 'app-user-list',
  standalone: true,
  imports: [
    CommonModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatDialogModule,
    MatSnackBarModule,
    LoadStateComponent
  ],
  templateUrl: './user-list.component.html',
  styleUrls: ['./user-list.component.scss']
})
export class UserList implements OnInit {
  private identityService = inject(IdentityService);
  private dialog = inject(MatDialog);
  private snackBar = inject(MatSnackBar);
  private cdr = inject(ChangeDetectorRef);

  displayedColumns: string[] = ['email', 'roles', 'admin', 'status', 'actions'];
  dataSource: User[] = [];

  /** Primeira carga em andamento / falha (uma recarga que falha mantém a tabela e só avisa). */
  isLoading = true;
  loadError: string | null = null;
  private loaded = false;

  ngOnInit(): void {
    this.loadData();
  }

  loadData() {
    if (!this.loaded) {
      this.isLoading = true;
      this.loadError = null;
    }
    this.identityService.getUsers().subscribe({
      next: (data) => {
        this.dataSource = data;
        this.loaded = true;
        this.isLoading = false;
        this.loadError = null;
        this.cdr.markForCheck();
      },
      error: (err) => {
        const msg = apiErrorMessage(err, 'Erro ao carregar usuários.');
        if (this.loaded) {
          this.snackBar.open(msg, 'Fechar', { duration: 4000 });
        } else {
          this.isLoading = false;
          this.loadError = msg;
        }
        this.cdr.markForCheck();
      }
    });
  }

  openDialog(user?: User) {
    const dialogRef = this.dialog.open(UserDialogComponent, {
      width: '500px',
      data: user || null
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        if (user) {
          // Remove password when updating to not break the API if empty
          delete result.password;
          this.identityService.updateUser(user.id, result).subscribe({
            next: () => this.loadData(),
            error: (err) => this.snackBar.open(apiErrorMessage(err, 'Erro ao salvar'), 'Fechar', { duration: 3000 })
          });
        } else {
          result.must_change_password = true;
          this.identityService.createUser(result).subscribe({
            next: () => this.loadData(),
            error: (err) => this.snackBar.open(apiErrorMessage(err, 'Erro ao salvar'), 'Fechar', { duration: 3000 })
          });
        }
      }
    });
  }

  openAccess(user: User) {
    this.dialog.open(UserAccessDialogComponent, { width: '720px', data: user });
  }

  resetPassword(id: string) {
    if (confirm('Gerar uma nova senha temporária para este usuário? As sessões atuais dele serão encerradas.')) {
      const temporary = generateTemporaryPassword();
      this.identityService.resetPassword(id, temporary).subscribe({
        next: () => {
          this.snackBar.open('Senha redefinida. O usuário deverá trocá-la no próximo acesso.', 'Fechar', { duration: 4000 });
          // a senha só existe agora: o prompt permite copiá-la; ela não é guardada em lugar nenhum
          window.prompt('Senha temporária (copie agora, ela não será exibida de novo):', temporary);
          this.loadData();
        },
        error: (err) => this.snackBar.open(apiErrorMessage(err, 'Erro ao redefinir a senha'), 'Fechar', { duration: 5000 })
      });
    }
  }

  deleteUser(id: string) {
    if (confirm('Tem certeza que deseja inativar/remover este usuário?')) {
      this.identityService.deleteUser(id).subscribe({
        next: () => this.loadData(),
        error: (err) => this.snackBar.open(apiErrorMessage(err, 'Erro ao inativar usuário'), 'Fechar', { duration: 5000 })
      });
    }
  }
}
