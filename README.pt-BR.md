<!-- generated-by: gsd-doc-writer -->
# Hermes Locker

[English](README.md) | [Português (Brasil)](README.pt-BR.md)

[![Licença: MIT](https://img.shields.io/badge/Licen%C3%A7a-MIT-yellow.svg)](LICENSE)

Plugin Secret Source do Hermes que resolve referências explícitas do Locker Secrets Manager no perfil Hermes ativo durante a inicialização.

## O que ele faz

- Mapeia variáveis de ambiente do Hermes para referências `locker://lower_snake_case`.
- Usa as credenciais bootstrap do perfil ativo ou uma credencial systemd protegida, com adesão explícita, para hidratação de perfis frios (0.3.0).
- Envia somente um ambiente mínimo e efêmero ao Locker CLI.
- Nunca imprime os valores resolvidos nem os grava na configuração do Hermes.
- Aplica um conjunto de mappings como uma única unidade: se uma consulta falhar ou retornar vazia, nenhum valor daquela passagem é retornado.

O plugin não mantém cache Python nem grava valores descriptografados por conta própria. O Locker CLI pode manter dados locais conforme sua implementação; o plugin usa `--refresh` em todas as consultas para exigir uma resposta atualizada do Locker.

## Requisitos

- Uma instalação do Hermes com suporte a plugins Secret Source.
- Locker CLI disponível no `PATH` da conta que executa o gateway.
- Uma access key do Locker com permissão de leitura em todos os secrets mapeados.

Esta versão foi validada com o Locker CLI 2.0.13.

## Instalação

### 1. Instale o Locker CLI

Siga as [instruções oficiais de download do Locker CLI](https://locker.io/secrets/download) e consulte a [documentação dos comandos de secrets](https://support.locker.io/en/locker-secrets-manager/developer-tools/secrets-commands-cli).

Não envie scripts remotos diretamente para o shell. Confirme o binário instalado:

```bash
locker --version
```

Execute essa verificação com a mesma conta de serviço e dentro do mesmo contêiner ou runtime que inicia o Hermes. Instalar o Locker CLI somente no host não o disponibiliza dentro de um contêiner do Hermes.

### 2. Crie a access key bootstrap do Hermes

Crie uma access key no Locker com permissão de leitura nos secrets que o Hermes resolverá. Não envie o valor secreto por chat, argumentos de comandos, logs ou controle de versão.

### 3. Provisione credenciais bootstrap protegidas

Os únicos nomes públicos de entrada suportados são `LOCKER_ACCESS_KEY_ID` e `LOCKER_ACCESS_KEY_SECRET`. Provisione o par correspondente por um mecanismo protegido de implantação; não armazene credenciais bootstrap em texto puro em `.env`, `config.yaml`, repositórios, workspaces de agentes, histórico do shell ou conversas.

Para um gateway systemd, provisione uma **credencial systemd criptografada** chamada `locker_bootstrap_env`. Seu payload UTF-8 descriptografado deve conter as duas atribuições canônicas `NAME=value`, uma vez cada, com valores não vazios. É um formato estrito de atribuições, não um script de shell: sem `export`, comentários, chaves adicionais ou expansão de shell. Envie o payload de um processo confiável de entrega de secrets diretamente para `systemd-creds encrypt --with-key=host --name=locker_bootstrap_env - <encrypted-output-path>` via stdin; nunca coloque valores reais em argumentos ou em um arquivo temporário em texto puro. Restrinja o arquivo criptografado ao administrador do serviço (por exemplo, proprietário root e modo `0600`).

Exemplo de drop-in do serviço (o caminho é ilustrativo e contém apenas dados criptografados):

```ini
[Service]
LoadCredentialEncrypted=locker_bootstrap_env:/etc/credstore.encrypted/locker_bootstrap_env
```

O systemd descriptografa e disponibiliza a credencial ao serviço. O plugin a lê diretamente após a adesão explícita do perfil abaixo; não é necessário exportar variáveis por wrapper nem usar `EnvironmentFile=%d/locker_bootstrap_env`. O `CREDENTIALS_DIRECTORY` do processo é apenas um **localizador de diretório não secreto**, não uma identidade bootstrap nem uma autorização. Não adicione secrets bootstrap a uma allowlist global de ambiente para fazer perfis frios funcionarem.

Na inicialização standalone sem essa adesão, o par canônico completo já deve estar disponível no ambiente ativo do Secret Source por injeção protegida. Injetá-lo somente no ambiente do processo de um gateway compartilhado **não** provisiona todos os perfis frios multiplexados. Consulte a [precedência bootstrap](#autenticação-bootstrap).

> `locker configure` continua opcional para uso manual do Locker CLI. Seu arquivo de credenciais não é lido pelo plugin; ele é distinto da credencial systemd com adesão explícita descrita acima.

### 4. Adicione os secrets ao Locker

Crie os secrets globais necessários no [painel do Locker](https://secrets.locker.io). Evite enviar valores secretos como argumentos de linha de comando.

### 5. Instale e habilite o plugin

```bash
hermes plugins install Company-OS-IA/hermes-locker-plugin --enable
```

Para uma instalação de produção reproduzível, acrescente `--ref` com o SHA revisado de um commit de 40 caracteres.

### 6. Configure o perfil Hermes ativo

Adicione mappings explícitos ao `config.yaml` do perfil:

```yaml
secrets:
  locker:
    enabled: true
    bootstrap_credential: locker_bootstrap_env
    override_existing: true
    timeout_seconds: 45
    env:
      MY_API_KEY: locker://my_api_key
      DATABASE_URL: locker://database_url
```

`bootstrap_credential` exige **adesão explícita**; não é o padrão. Inclua-o somente nos perfis autorizados a usar a identidade Locker compartilhada do serviço; omita-o quando usar um par bootstrap específico do perfil. Ele aceita um nome-base em lower_snake_case (no máximo 128 caracteres), nunca um caminho ou valor secreto. Instale/habilite o plugin e configure os mappings em cada perfil que precisar dele.

`secrets.sources` é opcional e não funciona como allowlist. Quando o Locker for o único source, omita essa lista como no exemplo acima: `enabled: true` é suficiente após a descoberta do plugin. Sources habilitados e ausentes da lista ainda são adicionados; use uma lista explícita somente quando a ordem entre vários Secret Sources for importante. Algumas versões do Hermes validam essa lista antes de descobrir plugins standalone e podem exibir o aviso transitório `unknown source(s): locker`.

`timeout_seconds` é o orçamento total de tempo para a resolução de todo o conjunto de mappings. O padrão do plugin é 15 segundos; use um valor maior ao resolver vários secrets remotos ou quando a API do Locker apresentar maior latência.

`cache_ttl_seconds` não é uma configuração do plugin Locker. Remova essa opção de configurações herdadas: o plugin deliberadamente não mantém cache Python e usa `--refresh` em todas as consultas.

### 7. Valide e reinicie

Para diagnóstico standalone pela CLI, use um ambiente protegido que contenha o par canônico (não exporte valores pelo histórico do shell):

```bash
hermes plugins show hermes-locker
hermes locker status
hermes locker status --probe-key my_api_key
hermes gateway restart
hermes gateway status
```

O probe recupera o valor selecionado, mas o descarta sem imprimi-lo. `hermes locker status` lê o ambiente do próprio processo; não lê `bootstrap_credential` nem exercita a hidratação de perfis frios. Um probe aprovado pela CLI **não comprova bootstrap frio multiplexado**; a ausência de chaves na CLI também pode coexistir com uma credencial systemd corretamente provisionada.

Após alterar o drop-in do serviço, recarregue o gerenciador systemd correspondente antes de reiniciar. Verifique um processo novo do gateway com escopos de perfis frios: cada perfil com adesão deve receber somente os nomes mapeados em sua configuração, um perfil sem par nem adesão não deve receber valores do Locker, e a integração dependente deve passar em uma verificação somente leitura. Inspecione apenas status, proveniência e nomes de variáveis, nunca valores. O Hermes pode memorizar falhas de hidratação por home; reinicie ou use uma limpeza de cache aprovada antes de retestar a configuração corrigida.

## Referência de configuração

| Configuração | Obrigatória | Padrão | Descrição |
|---|---:|---:|---|
| `enabled` | Sim | `false` | Habilita a resolução pelo Locker no perfil. |
| `env` | Sim | `{}` | Mappings explícitos entre variáveis de ambiente do Hermes e `locker://key`. |
| `bootstrap_credential` | Não | Ausente | Nome-base de uma credencial systemd protegida, mediante adesão explícita, por exemplo `locker_bootstrap_env`. |
| `override_existing` | Não | `true` | Permite que o Locker substitua valores antigos do shell ou `.env` nas variáveis mapeadas. |
| `timeout_seconds` | Não | `15` | Orçamento total de tempo para uma passagem completa de resolução. |

Os nomes das variáveis de ambiente devem corresponder a `[A-Z][A-Z0-9_]*`. As referências Locker devem usar snake case em minúsculas e ter no máximo 128 caracteres, por exemplo `locker://database_url`.

## Autenticação bootstrap

| Variável | Obrigatória | Finalidade |
|---|---:|---|
| `LOCKER_ACCESS_KEY_ID` | Sim | Identifica a access key usada pelo perfil ativo. |
| `LOCKER_ACCESS_KEY_SECRET` | Sim | Entrada canônica do secret correspondente; encaminhado somente pelo ambiente do subprocesso. |

Esses são os únicos nomes de entrada suportados pelo plugin, tanto no ambiente Secret Source do perfil quanto no payload systemd. Para compatibilidade com o protocolo do Locker CLI, o plugin traduz `LOCKER_ACCESS_KEY_SECRET` para `LOCKER_SECRET_ACCESS_KEY` **somente no ambiente do processo filho**, tanto nas resoluções quanto nos probes da CLI. `LOCKER_SECRET_ACCESS_KEY` **não é um alias de entrada suportado pelo plugin**; não o provisione no perfil nem no payload da credencial.

### Precedência e isolamento de perfis frios

A hidratação fria multiplexada do Hermes fornece um ambiente privado para cada perfil, em vez de herdar secrets arbitrários do processo do gateway. O plugin usa `get_source_environment()`:

1. Um par canônico completo e válido do perfil tem precedência; a credencial systemd não é aberta.
2. Se qualquer nome canônico existir, mas o par estiver parcial ou inválido (incluindo valores em branco, não textuais, com NUL ou quebras de linha), a resolução falha de forma fechada. Nunca mistura identidades de perfil e serviço nem recorre ao par compartilhado.
3. Somente quando **ambos os nomes estão ausentes** e `secrets.locker.bootstrap_credential` está explicitamente configurado, o plugin lê essa credencial sob o `CREDENTIALS_DIRECTORY` do processo.
4. Sem um par válido nem a credencial com adesão explícita, nenhum valor do Locker é retornado. Não há fallback para secrets globais do processo nem uma nova allowlist global de secrets na hidratação fria. Fora de uma resolução com escopo, o Hermes pode expor o ambiente do processo como ambiente do source; por isso o sucesso standalone é insuficiente.

O plugin não altera `os.environ` nem acrescenta valores bootstrap aos mappings resolvidos. Cada perfil recebe apenas seus mappings `env` explícitos pela hidratação por home e pelo `secret_scope` do Hermes. **Compartilhar uma identidade de serviço não cria ACLs distintas no cofre:** todos os perfis com adesão usam a mesma access key do Locker e suas permissões de leitura. Os mappings isolam a saída normal da hidratação, não a autorização do cofre contra um perfil capaz de alterar seus mappings ou executar código como a conta do serviço. Use identidades distintas de menor privilégio e limites separados de serviço/sistema operacional quando precisar de autorização independente no cofre.

### Leitura protegida da credencial

O diretório de credenciais deve ser absoluto, sem componentes vazios, `.` ou `..`. A travessia relativa a descritores usa aberturas no-follow para cada componente de diretório e para o arquivo. Os proprietários devem ser root ou o UID efetivo do serviço; ancestrais não podem permitir escrita por grupo/outros, exceto diretórios com sticky bit pertencentes a root. O diretório final deve negar todo acesso a grupo/outros. O arquivo deve ser regular, não executável e inacessível a grupo/outros (tipicamente `0400` ou `0600`), com tamanho informado e leitura limitada a 16.384 bytes. Links simbólicos, modos/proprietários inseguros, arquivos especiais, dados grandes demais, UTF-8 malformado, chaves duplicadas/desconhecidas e pares incompletos/inválidos falham de forma fechada, sem valores mapeados. Plataformas sem as flags necessárias de abertura segura também falham de forma fechada.

O plugin relê a credencial a cada resolução; o cache de hidratação por home do Hermes é separado. OAuth e arquivos de credenciais criados por `locker configure` continuam sem suporte na inicialização; o mecanismo systemd protegido é a exceção explícita para entrega bootstrap por arquivo.

## Comandos do operador

```bash
hermes locker setup --auth-mode access-keys
hermes locker status
hermes locker status --probe-key example_api_key
```

Esses comandos nunca instalam software, gravam credenciais, executam autenticação interativa ou imprimem os valores resolvidos.

## Limitações atuais

- Somente referências mapeadas explicitamente são suportadas; importação em massa não é suportada.
- A seleção de ambientes do Locker ainda não é exposta. As consultas usam o comportamento global de secrets do Locker.
- Arquivos de credenciais criados por `locker configure` não são usados na inicialização do Hermes.
- As consultas são sequenciais e compartilham o orçamento total de timeout configurado.

## Solução de problemas

| Sintoma | Causa | Correção |
|---|---|---|
| `unknown source(s): locker` | `secrets.sources` foi validado antes da descoberta do plugin standalone. | Omita a lista opcional `sources` quando o Locker for o único source. Se o Locker não for aplicado depois, atualize o Hermes e confirme que o plugin está habilitado no mesmo perfil. |
| `locker CLI: missing` | O binário não está disponível no runtime/contêiner ou no `PATH` do gateway. | Instale o Locker CLI nesse mesmo ambiente ou corrija o `PATH` do serviço. |
| `bootstrap access keys not configured` | Uma ou ambas as variáveis bootstrap estão ausentes do ambiente ativo do source. | Provisione o par completo por injeção protegida ou habilite a adesão do perfil frio a uma credencial systemd protegida e reinicie. |
| `Locker service bootstrap credential is unavailable or invalid` | A credencial com adesão explícita não pode ser lida com segurança ou seu payload é inválido. | Confira nome-base, `LoadCredentialEncrypted` do serviço, localizador, proprietários/modos e payload canônico sem imprimir valores. |
| `Locker bootstrap identity is incomplete or invalid` | Um campo bootstrap do perfil é inválido; um par parcial também bloqueia o fallback. | Corrija o par completo do perfil por provisionamento protegido; não espere fallback para a identidade compartilhada. |
| Probe da CLI passa, mas a resolução do perfil frio falha | Credenciais do processo da CLI não comprovam hidratação por perfil. | Confira descoberta do plugin, adesão/mappings do perfil e credencial do serviço em um processo novo do gateway; não coloque secrets em allowlist global. |
| `authentication probe: failed (invalid_access_key_id)` | O Locker não reconhece o ID informado. | Confira ou recrie a access key e atualize o ambiente do gateway. |
| `authentication probe: failed (unauthorized)` | O par ID/secret foi rejeitado ou não corresponde. | Configure o par correspondente em conjunto e reinicie o gateway. |
| `authentication probe: failed (forbidden)` | A autenticação funcionou, mas a chave não pode ler o secret solicitado. | Conceda permissão de leitura desse secret ou projeto à access key. |
| `fetch exceeded ... budget` | A passagem completa ultrapassou `timeout_seconds`. | Aumente `secrets.locker.timeout_seconds` e verifique a latência do Locker e da rede. |
| `Locker returned an empty mapped secret` | A chave existe, mas seu valor está vazio. | Defina um valor não vazio no Locker. |

## Validação de desenvolvimento

Execute em um clone com Hermes Agent e pytest disponíveis:

```bash
env -i PATH="$PWD/.venv/bin:/usr/local/bin:/usr/bin:/bin" \
    HOME=/nonexistent \
    PYTHONPATH=/usr/local/lib/hermes-agent \
    python -B -m pytest -q -p no:cacheprovider

hermes plugins doctor --ci
git diff --check
```

Ajuste somente o `PATH` do interpretador e o `PYTHONPATH` do código do Hermes conforme sua instalação. `env -i` inicia o processo de testes apenas com essas entradas mínimas de `PATH`, `HOME` e `PYTHONPATH`: sem credenciais herdadas nem `CREDENTIALS_DIRECTORY`. A suíte cria credenciais sintéticas e respostas simuladas do Locker; cobre leituras protegidas, precedência e hidratação fria/isolamento de perfis sem acesso real ao Locker. Nunca forneça credenciais reais aos testes. O plugin doctor é uma verificação separada de descoberta/conformidade, não uma comprovação de bootstrap frio multiplexado real.

## Licença

Distribuído sob a [Licença MIT](LICENSE).
