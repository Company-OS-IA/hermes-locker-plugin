<!-- generated-by: gsd-doc-writer -->
# Hermes Locker

[English](README.md) | [Português (Brasil)](README.pt-BR.md)

[![Licença: MIT](https://img.shields.io/badge/Licen%C3%A7a-MIT-yellow.svg)](LICENSE)

Plugin Secret Source do Hermes que resolve referências explícitas do Locker Secrets Manager no perfil Hermes ativo durante a inicialização.

## O que ele faz

- Mapeia variáveis de ambiente do Hermes para referências `locker://lower_snake_case`.
- Usa as credenciais bootstrap do perfil ativo, sem reutilizar valores globais armazenados em cache pelo Python.
- Envia somente um ambiente mínimo e efêmero ao Locker CLI.
- Nunca imprime os valores resolvidos nem os grava na configuração do Hermes.
- Aplica um conjunto de mappings como uma única unidade: se uma consulta falhar ou retornar vazia, nenhum valor daquela passagem é retornado.
- Aceita o nome legado `LOCKER_SECRET_ACCESS_KEY`, normalizando-o somente no ambiente do subprocesso Locker.

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

### 2. Crie a access key bootstrap do Hermes

Crie uma access key no Locker com permissão de leitura nos secrets que o Hermes resolverá. Não envie o valor secreto por chat, argumentos de comandos, logs ou controle de versão.

### 3. Adicione as variáveis bootstrap ao Hermes

O processo do gateway precisa receber as duas variáveis antes de o plugin ser habilitado:

```dotenv
LOCKER_ACCESS_KEY_ID=seu_access_key_id
LOCKER_ACCESS_KEY_SECRET=seu_secret_access_key
```

Em uma instalação padrão, coloque-as no arquivo `.env` do perfil Hermes ativo:

```text
~/.hermes/.env
```

Exemplos:

- Um gateway executado como `root` usa `/root/.hermes/.env`.
- Um gateway executado por outra conta de serviço usa o `~/.hermes/.env` desse usuário.
- Um perfil Hermes nomeado usa seu `HERMES_HOME/.env` ativo.

Abra o arquivo com um editor controlado pelo operador, adicione as duas variáveis e restrinja o acesso à conta do gateway:

```bash
chmod 600 ~/.hermes/.env
```

Não coloque esses valores em `config.yaml`, na configuração do plugin, em repositórios, no histórico do shell ou em conversas com agentes. Um agente de instalação deve verificar somente se os nomes das duas variáveis estão presentes. Se alguma estiver ausente, ele deve solicitar que o operador a configure sem ler ou imprimir seu valor.

Um `EnvironmentFile` do systemd, secrets de contêiner e gerenciadores de secrets da plataforma também são válidos quando injetam as duas variáveis no processo do gateway.

> `locker configure` é opcional para o uso manual do Locker CLI. O arquivo de credenciais criado por ele não é utilizado por este plugin; o Hermes ainda exige as duas variáveis acima no ambiente protegido.

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
  sources: [locker]
  locker:
    enabled: true
    override_existing: true
    timeout_seconds: 45
    env:
      MY_API_KEY: locker://my_api_key
      DATABASE_URL: locker://database_url
```

`timeout_seconds` é o orçamento total de tempo para a resolução de todo o conjunto de mappings. O padrão do plugin é 15 segundos; use um valor maior ao resolver vários secrets remotos ou quando a API do Locker apresentar maior latência.

### 7. Valide e reinicie

Execute o probe em um ambiente que carregue o mesmo `.env` do perfil Hermes ativo:

```bash
hermes plugins show hermes-locker
hermes locker status
hermes locker status --probe-key my_api_key
hermes gateway restart
hermes gateway status
```

O probe recupera o valor selecionado, mas o descarta sem imprimi-lo.

## Referência de configuração

| Configuração | Obrigatória | Padrão | Descrição |
|---|---:|---:|---|
| `enabled` | Sim | `false` | Habilita a resolução pelo Locker no perfil. |
| `env` | Sim | `{}` | Mappings explícitos entre variáveis de ambiente do Hermes e `locker://key`. |
| `override_existing` | Não | `true` | Permite que o Locker substitua valores antigos do shell ou `.env` nas variáveis mapeadas. |
| `timeout_seconds` | Não | `15` | Orçamento total de tempo para uma passagem completa de resolução. |

Os nomes das variáveis de ambiente devem corresponder a `[A-Z][A-Z0-9_]*`. As referências Locker devem usar snake case em minúsculas e ter no máximo 128 caracteres, por exemplo `locker://database_url`.

## Autenticação bootstrap

| Variável | Obrigatória | Finalidade |
|---|---:|---|
| `LOCKER_ACCESS_KEY_ID` | Sim | Identifica a access key usada pelo perfil ativo. |
| `LOCKER_ACCESS_KEY_SECRET` | Sim | Fornece o secret correspondente somente pelo ambiente do subprocesso. |
| `LOCKER_SECRET_ACCESS_KEY` | Apenas legado | Aceita como nome antigo e normaliza de forma efêmera. |

O Locker CLI aceita flags e arquivos de credenciais, mas o plugin exige deliberadamente credenciais bootstrap de ambiente vinculadas ao perfil. OAuth e arquivos de credenciais não são suportados na inicialização deste plugin.

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
| `locker CLI: missing` | O binário não está no `PATH` da conta do gateway. | Instale o Locker CLI ou corrija o `PATH` do serviço. |
| `bootstrap access keys not configured` | Uma ou ambas as variáveis bootstrap estão ausentes do ambiente Hermes ativo. | Adicione as duas variáveis ao `.env` do perfil ativo ou ao ambiente protegido do serviço e reinicie. |
| `authentication probe: failed (invalid_access_key_id)` | O Locker não reconhece o ID informado. | Confira ou recrie a access key e atualize o ambiente do gateway. |
| `authentication probe: failed (unauthorized)` | O par ID/secret foi rejeitado ou não corresponde. | Configure o par correspondente em conjunto e reinicie o gateway. |
| `authentication probe: failed (forbidden)` | A autenticação funcionou, mas a chave não pode ler o secret solicitado. | Conceda permissão de leitura desse secret ou projeto à access key. |
| `fetch exceeded ... budget` | A passagem completa ultrapassou `timeout_seconds`. | Aumente `secrets.locker.timeout_seconds` e verifique a latência do Locker e da rede. |
| `Locker returned an empty mapped secret` | A chave existe, mas seu valor está vazio. | Defina um valor não vazio no Locker. |

## Validação de desenvolvimento

Execute em um clone com Hermes Agent e pytest disponíveis:

```bash
env -u LOCKER_ACCESS_KEY_ID \
    -u LOCKER_ACCESS_KEY_SECRET \
    -u LOCKER_SECRET_ACCESS_KEY \
    PYTHONPATH=/usr/local/lib/hermes-agent \
    python -m pytest -q

hermes plugins doctor --ci
git diff --check
```

Os testes usam valores sintéticos e limpam as três variáveis bootstrap do Locker em cada caso. Nunca use credenciais de produção na suíte de testes.

## Licença

Distribuído sob a [Licença MIT](LICENSE).
